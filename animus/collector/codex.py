"""Read-only Codex sources with acknowledged, at-least-once checkpoints."""
from __future__ import annotations

import hashlib
import json
import ntpath
import os
import re
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ..obsidian import _sensitive_findings
from .models import Memory, MemoryType

MAX_CYCLE_BYTES = 64 * 1024**2
MAX_SLICE_BYTES = 4 * 1024**2
MAX_LINE_BYTES = 1024**2
MAX_TEXT_CHARS = 16384
MAX_MESSAGES = 1000
MAX_SOURCES = 20


def workspace_path(value: str) -> str:
    value = str(value)
    if re.match(r'^(?:[a-zA-Z]:[\\/]|\\\\)', value):
        value = value.replace('/', '\\')
        if value.startswith('\\\\?\\UNC\\'):
            value = '\\\\' + value[8:]
        elif value.startswith('\\\\?\\'):
            value = value[4:]
        if os.name == 'nt' and re.match(r'^[a-zA-Z]:\\', value):
            # Resolve local junctions too: lexical prefix alone is not consent.
            value = str(Path(value).resolve())
            value = value.removeprefix('\\\\?\\')
        return ntpath.normcase(ntpath.normpath(value))
    return str(Path(value).resolve())


@contextmanager
def readonly(path: Path):
    # immutable=1 would hide uncheckpointed WAL data from the running Codex.
    conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
    try:
        conn.execute('PRAGMA query_only=ON')
        deadline = time.monotonic() + 2
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        yield conn
    finally:
        conn.close()


class CodexCollector:
    def __init__(self, config):
        self.config = config
        self.diagnostics: dict[str, int] = {}
        self._pending: dict | None = None
        self._scope_cache: dict[tuple, bool] = {}

    def count(self, key, count=1):
        self.diagnostics[key] = self.diagnostics.get(key, 0) + count

    @property
    def checkpoint_path(self):
        scope = [str(self.config.codex_data_dir.resolve()),
                 sorted(workspace_path(str(p)) for p in self.config.codex_allowed_workspaces),
                 self.config.collect_codex_memories]
        digest = hashlib.sha256(json.dumps(scope).encode()).hexdigest()[:16]
        return self.config.data_dir / f'codex-checkpoints-{digest}.json'

    def acknowledge(self):
        """Called only after indexing. Concurrent stale writers cause replay, not loss."""
        if self._pending is None:
            return
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.codex-checkpoint-', dir=self.config.data_dir)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(self._pending, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.checkpoint_path)
            self._pending = None
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def collect_all(self):
        self.diagnostics = {}
        self._pending = None
        self._scope_cache = {}
        if not self.config.collect_codex_chat or not self.config.codex_allowed_workspaces:
            return []
        try:
            state = json.loads(self.checkpoint_path.read_text('utf-8'))
            if state.get('version') != 1 or not isinstance(state.get('sources'), dict):
                raise ValueError('Unsupported checkpoint')
        except (OSError, ValueError, AttributeError):
            state = {'version': 1, 'sources': {}}
        sources = state['sources']
        result, paths, consumed = [], [], 0
        for directory in ('sessions', 'archived_sessions'):
            root = self.config.codex_data_dir / directory
            if root.is_dir():
                paths.extend(p for p in root.rglob('*.jsonl') if self.safe_file(p))
        # Oldest visit first; active/large sessions cannot starve other sources.
        paths.sort(key=lambda p: (sources.get(str(p), {}).get('visited', 0), str(p)))
        for path in paths[:MAX_SOURCES]:
            if consumed >= MAX_CYCLE_BYTES or len(result) >= MAX_MESSAGES:
                break
            cursor = dict(sources.get(str(path), {}))
            try:
                rows, cursor, size = self.read_session(path, cursor,
                    min(MAX_SLICE_BYTES, MAX_CYCLE_BYTES - consumed), MAX_MESSAGES - len(result))
            except (OSError, UnicodeError, ValueError):
                self.count('unreadable_sessions')
                cursor['visited'] = time.time_ns()
                sources[str(path)] = cursor
                continue
            consumed += size
            result.extend(rows)
            cursor['visited'] = time.time_ns()
            sources[str(path)] = cursor
        result.extend(self.history(sources))
        if self.config.collect_codex_memories:
            result.extend(self.summaries(sources))
        self._pending = state
        self.count('session_bytes_read', consumed)
        return list({row.id: row for row in result}.values())

    @staticmethod
    def safe_file(path):
        try:
            return path.is_file() and not path.is_symlink() and path.resolve() == path.absolute()
        except OSError:
            return False

    def _allowed(self, cwd):
        if not isinstance(cwd, str) or not cwd or any(ord(char) < 32 for char in cwd):
            return False
        key = (cwd, tuple(str(root) for root in self.config.codex_allowed_workspaces))
        if key in self._scope_cache:
            return self._scope_cache[key]
        try:
            path = workspace_path(cwd)
        except (OSError, ValueError, RuntimeError):
            return False
        for root in self.config.codex_allowed_workspaces:
            allowed = workspace_path(str(root))
            sep = '\\' if re.match(r'^(?:[a-z]:|\\\\)', allowed) else os.sep
            if path == allowed or path.startswith(allowed.rstrip(sep) + sep):
                self._scope_cache[key] = True
                return True
        self._scope_cache[key] = False
        return False

    def message(self, session, cwd, sequence, role, phase, text, stamp, *, summary=False):
        if not isinstance(session, str) or not session or not self._allowed(cwd):
            return None
        if role not in ('user', 'assistant') or not isinstance(text, str):
            return None
        if role == 'assistant' and phase not in ('final_answer', 'final'):
            return None
        text = re.sub(r'<oai-mem-citation>.*?</oai-mem-citation>', '', text, flags=re.DOTALL).strip()
        if len(text) > MAX_TEXT_CHARS:
            self.count('oversized_text_skipped')
            return None
        if not text or any(marker in text for marker in (
            '<environment_context>', '<external_codex_apps_open_page>', '# AGENTS.md instructions',
            '<INSTRUCTIONS>', '<system-reminder>', '<in-app-browser-context>',
        )):
            return None
        if _sensitive_findings(text):
            self.count('sensitive_messages_skipped')
            return None
        try:
            stamp = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                return None
        except (ValueError, TypeError, AttributeError):
            return None
        source = f'codex://{session}/{sequence}'
        if summary:
            source = f'codex-memory://{session}/{hashlib.sha256(text.encode()).hexdigest()}'
        metadata = {'session_id': session, 'role': 'summary' if summary else role, 'source': 'codex',
                    'status': 'candidato', 'sensibilidade': 'interno'}
        if summary:
            metadata['artifact'] = 'generated_memory'
        return Memory(type=MemoryType.CODEX_CHAT, source_node=self.config.node_id, source_path=source,
            workspace=ntpath.basename(workspace_path(cwd)), timestamp=stamp.astimezone(timezone.utc),
            title=f'Codex {"memory" if summary else role}: {text.splitlines()[0][:100]}',
            content=text, sequence=sequence, metadata=metadata)

    @staticmethod
    def parts(parts):
        if not isinstance(parts, list):
            return ''
        return '\n'.join(p['text'] for p in parts if isinstance(p, dict)
            and p.get('type') in ('input_text', 'output_text', 'text') and isinstance(p.get('text'), str))

    def read_session(self, path, cursor, budget, limit):
        rows = []
        stat = path.stat()
        with path.open('rb') as stream:
            head = hashlib.sha256(stream.read(256)).hexdigest()
            if (cursor.get('head') != head or cursor.get('offset', 0) > stat.st_size
                    or (cursor.get('offset') == stat.st_size
                        and cursor.get('mtime') != stat.st_mtime_ns)):
                cursor = {}
            stream.seek(cursor.get('offset', 0))
            start = stream.tell()
            while stream.tell() - start + MAX_LINE_BYTES + 1 <= budget and len(rows) < limit:
                position = stream.tell()
                raw = stream.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    break
                if cursor.get('draining'):
                    cursor['draining'] = not raw.endswith(b'\n')
                    cursor['offset'] = stream.tell()
                    continue
                if not raw.endswith(b'\n'):
                    if len(raw) > MAX_LINE_BYTES:
                        cursor['sequence'] = cursor.get('sequence', 0) + 1
                        cursor['draining'] = True
                        cursor['offset'] = stream.tell()
                        self.count('oversized_records_skipped')
                        continue
                    stream.seek(position)
                    break  # partial append: retry the whole record next cycle
                cursor['sequence'] = cursor.get('sequence', 0) + 1
                cursor['offset'] = stream.tell()
                try:
                    record = json.loads(raw)
                except (ValueError, UnicodeError):
                    self.count('malformed_records')
                    continue
                if not isinstance(record, dict) or not isinstance(record.get('payload'), dict):
                    continue
                payload = record['payload']
                if record.get('type') == 'session_meta':
                    cursor['session'], cursor['cwd'] = payload.get('id', ''), payload.get('cwd', '')
                elif record.get('type') == 'turn_context':
                    cursor['cwd'] = payload.get('cwd', '')
                elif record.get('type') == 'response_item' and payload.get('type') == 'message':
                    row = self.message(cursor.get('session', ''), cursor.get('cwd', ''),
                        cursor['sequence'], payload.get('role'), payload.get('phase', payload.get('channel')),
                        self.parts(payload.get('content')), record.get('timestamp'))
                    if row:
                        rows.append(row)
            consumed = stream.tell() - start
        cursor.update(head=head, mtime=stat.st_mtime_ns)
        return rows, cursor, consumed

    def collect_session(self, path):
        """Stateless compatibility probe; production uses acknowledged slices."""
        return self.read_session(path, {}, MAX_CYCLE_BYTES, MAX_MESSAGES)[0]

    def history(self, sources):
        root = self.config.codex_data_dir
        state_path, history_path = root / 'state_5.sqlite', root / 'thread_history_1.sqlite'
        if not self.safe_file(state_path) or not self.safe_file(history_path):
            return []
        result = []
        try:
            with readonly(state_path) as state:
                threads = state.execute('SELECT id, cwd, rollout_path, source FROM threads LIMIT 10000').fetchall()
            threads = [t for t in threads if self._allowed(t[1])
                       and not str(t[3]).startswith('{')
                       and (not t[2] or not Path(t[2]).is_file())]
            threads.sort(key=lambda t: (sources.get('history:' + t[0], {}).get('visited', 0), t[0]))
            with readonly(history_path) as history:
                for session, cwd, _, _ in threads[:MAX_SOURCES]:
                    key = 'history:' + session
                    cursor = dict(sources.get(key, {}))
                    rows = history.execute('''SELECT rollout_ordinal, updated_at_ordinal, created_at_ms,
                        CASE WHEN length(item_json) <= ? THEN item_json END
                        FROM thread_items WHERE thread_id=? AND updated_at_ordinal>?
                        AND item_type IN ('userMessage', 'agentMessage')
                        ORDER BY updated_at_ordinal LIMIT 100''',
                        (128 * 1024, session, cursor.get('ordinal', -1))).fetchall()
                    for ordinal, updated, created, raw in rows:
                        if raw:
                            try:
                                item = json.loads(raw)
                                if not isinstance(item, dict):
                                    raise TypeError('Invalid history item')
                                role = 'user' if item.get('type') == 'userMessage' else 'assistant'
                                text = self.parts(item.get('content')) if role == 'user' else item.get('text', '')
                                stamp = datetime.fromtimestamp(created / 1000, timezone.utc).isoformat()
                                row = self.message(session, cwd, ordinal, role, item.get('phase'), text, stamp)
                                if row:
                                    result.append(row)
                            except (ValueError, TypeError, AttributeError, OverflowError, OSError):
                                self.count('malformed_history_items')
                        cursor['ordinal'] = updated
                    cursor['visited'] = time.time_ns()
                    sources[key] = cursor
        except (sqlite3.Error, OSError):
            self.count('history_unavailable')
        return result

    def summaries(self, sources):
        result, paths = [], []
        for store in ('memories', 'memories_v2'):
            paths.extend(p for p in (self.config.codex_data_dir / store / 'rollout_summaries').glob('*.md')
                         if self.safe_file(p))
        paths.sort(key=lambda p: (sources.get(str(p), {}).get('visited', 0), str(p)))
        for path in paths[:MAX_SOURCES]:
            try:
                stat = path.stat()
                if stat.st_size > MAX_LINE_BYTES:
                    self.count('oversized_summaries_skipped')
                    sources[str(path)] = {'visited': time.time_ns()}
                    continue
                signature = [stat.st_size, stat.st_mtime_ns]
                if sources.get(str(path), {}).get('signature') != signature:
                    text = path.read_text('utf-8-sig')
                    header, separator, body = text.partition('\n\n')
                    fields = dict(line.split(': ', 1) for line in header.splitlines() if ': ' in line)
                    cwd, session = fields.get('cwd', ''), fields.get('thread_id', '')
                    if separator and session and self._allowed(cwd):
                        if _sensitive_findings(body):
                            self.count('sensitive_summaries_skipped')
                            sources[str(path)] = {'signature': signature, 'visited': time.time_ns()}
                            continue
                        chunks, chunk = [], ''
                        for paragraph in body.split('\n\n'):
                            if len(chunk) + len(paragraph) + 2 > MAX_TEXT_CHARS:
                                chunks.append(chunk.strip())
                                chunk = ''
                            chunk += paragraph + '\n\n'
                        chunks.append(chunk.strip())
                        for part in chunks:
                            row = self.message(session, cwd, 0, 'user', None, part,
                                fields.get('updated_at'), summary=True)
                            if row:
                                result.append(row)
                sources[str(path)] = {'signature': signature, 'visited': time.time_ns()}
            except (OSError, UnicodeError, ValueError):
                self.count('unreadable_summaries')
        return result
