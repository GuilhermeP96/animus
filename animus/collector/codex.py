"""Opt-in, workspace-scoped collection of Codex user/final-answer messages.

Never index reasoning, developer/system instructions, tool calls/results, images
or token logs. Source messages are evidence, not verified Obsidian knowledge.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import time

from ..config import AnimusConfig
from ..obsidian import _sensitive_findings
from .models import Memory, MemoryType

MAX_FILE_BYTES = 64 * 1024**2
MAX_CYCLE_BYTES = 64 * 1024**2
MAX_LINE_BYTES = 1024**2
MAX_TEXT_CHARS = 16384


class CodexCollector:
    def __init__(self, config: AnimusConfig):
        self.config = config
        self.diagnostics: dict[str, int] = {}

    def collect_all(self) -> list[Memory]:
        self.diagnostics = {}
        if not self.config.collect_codex_chat or not self.config.codex_allowed_workspaces:
            return []
        root = self.config.codex_data_dir / 'sessions'
        if not root.is_dir():
            return []
        cutoff = time.time() - 7 * 86400
        candidates = []
        for path in root.rglob('*.jsonl'):
            try:
                if path.is_symlink() or path.resolve() != path.absolute():
                    continue
                stat = path.stat()
                if stat.st_mtime >= cutoff and stat.st_size <= MAX_FILE_BYTES:
                    candidates.append((stat.st_mtime, stat.st_size, path))
            except OSError:
                continue
        result, consumed = [], 0
        for _, size, path in sorted(candidates, reverse=True)[:20]:
            if consumed + size > MAX_CYCLE_BYTES:
                continue
            consumed += size
            try:
                result.extend(self.collect_session(path))
            except (OSError, UnicodeError):
                self.diagnostics['unreadable_sessions'] = self.diagnostics.get('unreadable_sessions', 0) + 1
        return result

    def _allowed(self, cwd: str) -> bool:
        if not cwd:
            return False
        path = Path(cwd).resolve()
        return any(path == Path(root).resolve() or Path(root).resolve() in path.parents
                   for root in self.config.codex_allowed_workspaces)

    def collect_session(self, path: Path) -> list[Memory]:
        session, cwd = '', ''
        rows: deque[Memory] = deque(maxlen=40)
        with path.open('rb') as stream:
            sequence, budget = 0, MAX_FILE_BYTES
            while budget > 0:
                raw = stream.readline(min(MAX_LINE_BYTES + 1, budget))
                if not raw:
                    break
                budget -= len(raw)
                if not raw.endswith(b'\n') and len(raw) >= MAX_LINE_BYTES:
                    # Drain an oversized record without allocating it or parsing its suffix.
                    while raw and not raw.endswith(b'\n') and budget > 0:
                        raw = stream.readline(min(MAX_LINE_BYTES, budget))
                        budget -= len(raw)
                    continue
                sequence += 1
                try:
                    record = json.loads(raw)
                except (ValueError, UnicodeError):
                    continue  # also tolerates an append-in-progress final line
                payload = record.get('payload')
                if not isinstance(payload, dict):
                    continue
                if record.get('type') == 'session_meta':
                    session, cwd = str(payload.get('id', '')), str(payload.get('cwd', ''))
                    continue
                if record.get('type') == 'turn_context':
                    cwd = str(payload.get('cwd', ''))
                    continue
                if not session or record.get('type') != 'response_item':
                    continue
                role = payload.get('role')
                if payload.get('type') != 'message' or role not in ('user', 'assistant'):
                    continue
                if role == 'assistant' and payload.get('phase', payload.get('channel')) not in ('final_answer', 'final'):
                    continue
                if not self._allowed(cwd):
                    continue
                parts = payload.get('content', [])
                text = '\n'.join(p.get('text', '') for p in parts if isinstance(p, dict)
                                 and p.get('type') in ('input_text', 'output_text', 'text'))
                text = re.sub(r'<oai-mem-citation>.*?</oai-mem-citation>', '', text, flags=re.S).strip()
                # Context envelopes/instructions and overlong messages are not durable conversation turns.
                if not text.strip() or len(text) > MAX_TEXT_CHARS or any(marker in text for marker in (
                    '<environment_context>', '<external_codex_apps_open_page>', '# AGENTS.md instructions',
                    '<INSTRUCTIONS>', '<system-reminder>',
                )):
                    continue
                if _sensitive_findings(text):
                    self.diagnostics['sensitive_messages_skipped'] = self.diagnostics.get('sensitive_messages_skipped', 0) + 1
                    continue
                try:
                    stamp = datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00'))
                except (KeyError, ValueError, TypeError):
                    continue
                rows.append(Memory(type=MemoryType.CODEX_CHAT, source_node=self.config.node_id,
                    source_path=f'codex://{session}/{sequence}', workspace=Path(cwd).name,
                    timestamp=stamp.astimezone(timezone.utc), title=f'Codex {role}: {text.splitlines()[0][:100]}',
                    content=text, sequence=sequence,
                    metadata={'session_id': session, 'role': role, 'source': 'codex',
                              'status': 'candidato', 'sensibilidade': 'interno'}))
        return list(rows)
