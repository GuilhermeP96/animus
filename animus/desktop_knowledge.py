"""Private JSON/stdio bridge for the Windows knowledge window.

No listener, second vault, copied database or credentials in the desktop. Every
operation uses the configured vault and the same peer index/update queue.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import posixpath
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote

from .collector.obsidian import (
    ObsidianCollector,
    extract_links,
    memory_from_note,
    note_id,
    parse_frontmatter,
)
from .config import AnimusConfig
from .indexer.engine import IndexEngine
from .obsidian import ObsidianManager, _atomic_write, _sensitive_findings, sanitize_title

MAX_NOTE_BYTES = 512 * 1024
MAX_REQUEST_BYTES = 4 * 1024**2
MAX_SCAN_BYTES = 24 * 1024**2
MAX_FILES = 5000
MAX_NAV_NOTES = 2000
STATUSES = ("candidato", "curado", "verificado", "depreciado")
SENSITIVITIES = ("publico", "interno", "restrito")
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
MAX_IMAGE_BYTES = 2 * 1024**2
FIELDS = ("title", "projeto", "status", "sensibilidade")


class KnowledgeConflict(ValueError):
    pass


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reparse(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


@contextmanager
def _windows_source(path):
    """Deny other writers and rename/delete while committing the original file."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    handle = create(str(path), 0xC0000000, 1, None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        raise KnowledgeConflict("source busy")
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
    except Exception:
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(fd, "r+b") as stream:
        yield stream


@contextmanager
def _edit_lock(data: Path, key: str):
    data.mkdir(parents=True, exist_ok=True)
    path = data / ("knowledge-" + hashlib.sha256(key.encode()).hexdigest()[:24] + ".lock")
    if _reparse(path):
        raise PermissionError("invalid lock")
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class KnowledgeService:
    def __init__(self, config: AnimusConfig, engine: IndexEngine):
        self.config, self.engine = config, engine
        self.manager = ObsidianManager(config, engine)
        self.collector = ObsidianCollector(config)

    def _vault(self, name, *, write=False):
        if not isinstance(name, str):
            raise TypeError("invalid vault")
        vault = self.manager.vault(name)
        if write and (not self.config.collect_obsidian or not vault.enabled):
            raise PermissionError("collection disabled")
        return vault

    def _target(self, vault, relative: str) -> Path:
        if not isinstance(relative, str) or any(ord(x) < 32 for x in relative):
            raise PermissionError("invalid note path")
        relative = relative.replace("\\", "/")
        parts = relative.split("/")
        if (
            not relative
            or any(p in ("", ".", "..") or ":" in p for p in parts)
            or not relative.lower().endswith(".md")
            or self.collector._excluded(relative)
        ):
            raise PermissionError("excluded note path")
        path = vault.path.joinpath(*parts)
        resolved = path.resolve()
        if vault.path not in resolved.parents:
            raise PermissionError("outside vault")
        for parent in (path, *path.parents):
            if parent == vault.path:
                break
            if _reparse(parent):
                raise PermissionError("note link refused")
        return resolved

    def _read(self, vault, relative):
        path = self._target(vault, relative)
        if path.stat().st_size > MAX_NOTE_BYTES:
            raise ValueError("note too large")
        raw = path.read_bytes()
        if len(raw) > MAX_NOTE_BYTES:
            raise ValueError("note too large")
        text = raw.decode("utf-8-sig")
        meta, body, warning = parse_frontmatter(text)
        return path, raw, text, meta, body, warning

    def status(self):
        count = self.engine.conn.execute(
            "SELECT count(*) FROM memories WHERE type='obsidian_note' AND synced=0"
        ).fetchone()[0]
        return {
            "vaults": [
                {
                    "name": v.name,
                    "enabled": v.enabled,
                    "editable": bool(self.config.collect_obsidian and v.enabled),
                    "available": v.path.expanduser().is_dir(),
                }
                for v in self.config.obsidian_vaults
            ],
            "collection_enabled": self.config.collect_obsidian,
            "pending_notes": count,
        }

    def _resolve_reference(self, vault, current, reference, *, image=False):
        if not isinstance(reference, str) or len(reference) > 2000:
            raise ValueError("invalid reference")
        reference = unquote(reference.split("#", 1)[0]).replace("\\", "/")
        if (
            not reference
            or reference.startswith("/")
            or ":" in reference
            or any(ord(c) < 32 for c in reference)
        ):
            raise PermissionError("external reference refused")
        if not image and not reference.lower().endswith(".md"):
            reference += ".md"
        current = current.replace("\\", "/") if isinstance(current, str) else ""
        parent = posixpath.dirname(current)
        candidates = [
            posixpath.normpath(posixpath.join(parent, reference)),
            posixpath.normpath(reference),
        ]

        def safe(relative):
            if image:
                parts = relative.split("/")
                if any(
                    p in ("", "..", ".") or ":" in p or p.casefold() in {".git", ".obsidian"}
                    for p in parts
                ):
                    raise PermissionError("invalid attachment path")
                folded = [p.casefold() for p in parts]
                if ".animus" in folded and (
                    folded[:3] != [".animus", "exported", "conhecimento"]
                    or ".animus" in folded[1:]
                ):
                    raise PermissionError("internal attachment path")
                path = vault.path.joinpath(*parts)
                if (
                    path.suffix.lower() not in IMAGE_TYPES
                    or vault.path not in path.resolve().parents
                ):
                    raise PermissionError("unsupported attachment")
                for p in (path, *path.parents):
                    if p == vault.path:
                        break
                    if _reparse(p):
                        raise PermissionError("attachment link refused")
                return path.resolve()
            return self._target(vault, relative)

        for relative in dict.fromkeys(candidates):
            try:
                target = safe(relative)
                if target.is_file():
                    return target
            except (PermissionError, OSError):
                continue
        if "/" not in reference:
            matches = []
            visited = 0
            for directory, dirs, files in os.walk(vault.path, followlinks=False):
                dirs[:] = [
                    d
                    for d in dirs
                    if d.casefold() not in {".git", ".obsidian", "node_modules"}
                    and not _reparse(Path(directory) / d)
                    and (
                        ".animus"
                        not in (Path(directory) / d)
                        .relative_to(vault.path)
                        .as_posix()
                        .casefold()
                        .split("/")
                        or ".animus/exported/conhecimento/".startswith(
                            (Path(directory) / d).relative_to(vault.path).as_posix().casefold()
                            + "/"
                        )
                        or (Path(directory) / d)
                        .relative_to(vault.path)
                        .as_posix()
                        .casefold()
                        .startswith(".animus/exported/conhecimento/")
                    )
                ]
                for name in files:
                    visited += 1
                    if visited > MAX_FILES:
                        raise ValueError("reference scan limit")
                    if name.casefold() != reference.casefold():
                        continue
                    try:
                        target = safe((Path(directory) / name).relative_to(vault.path).as_posix())
                    except (PermissionError, OSError):
                        continue
                    matches.append(target)
                    if len(set(matches)) > 1:
                        raise ValueError("ambiguous reference")
            if len(set(matches)) == 1:
                return matches[0]
        raise ValueError("reference unavailable")

    def resolve(self, vault_name, current, reference):
        vault = self._vault(vault_name)
        target = self._resolve_reference(vault, current, reference)
        return self.read(vault_name, target.relative_to(vault.path).as_posix())

    def attachment(self, vault_name, current, reference):
        vault = self._vault(vault_name)
        path = self._resolve_reference(vault, current, reference, image=True)
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError("attachment too large")
        raw = path.read_bytes()
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("attachment too large")
        suffix = path.suffix.lower()
        valid = (
            suffix == ".png"
            and raw.startswith(b"\x89PNG\r\n\x1a\n")
            or suffix in {".jpg", ".jpeg"}
            and raw.startswith(b"\xff\xd8\xff")
            or suffix == ".gif"
            and raw.startswith((b"GIF87a", b"GIF89a"))
            or suffix == ".webp"
            and raw.startswith(b"RIFF")
            and raw[8:12] == b"WEBP"
        )
        if suffix == ".svg":
            svg_text = raw.decode("utf-8-sig")
            if "<!DOCTYPE" in svg_text.upper() or "<!ENTITY" in svg_text.upper():
                raise ValueError("unsafe SVG")
            try:
                valid = ET.fromstring(svg_text).tag in {"svg", "{http://www.w3.org/2000/svg}svg"}
            except ET.ParseError as exc:
                raise ValueError("invalid SVG") from exc
        if not valid:
            raise ValueError("invalid image")
        return {
            "data_url": "data:"
            + IMAGE_TYPES[suffix]
            + ";base64,"
            + base64.b64encode(raw).decode("ascii")
        }

    def read(self, vault_name, relative):
        relative = relative.replace("\\", "/") if isinstance(relative, str) else relative
        vault = self._vault(vault_name)
        path, raw, _, meta, body, warning = self._read(vault, relative)
        relative = path.relative_to(vault.path).as_posix()
        row = self.engine.get_memory(note_id(vault.name, relative))
        training = meta.get("treino", {})
        training_approved = isinstance(training, dict) and training.get("aprovado") is True
        canonical = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        indexed = bool(
            row and json.loads(row.get("metadata") or "{}").get("content_hash") == digest(canonical)
        )
        return {
            "vault": vault.name,
            "path": relative,
            "etag": digest(raw),
            "body": body,
            "title": str(meta.get("title") or path.stem),
            "projeto": str(meta.get("projeto") or ""),
            "status": str(meta.get("status") or "candidato"),
            "sensibilidade": str(meta.get("sensibilidade") or "interno"),
            "editable": bool(
                self.config.collect_obsidian
                and vault.enabled
                and not warning
                and not training_approved
            ),
            "warning": (
                "Metadados YAML precisam ser corrigidos na origem."
                if warning
                else "Nota aprovada para treino: revise essa aprovação na origem antes de editar."
                if training_approved
                else ""
            ),
            "sync_state": "synced"
            if indexed and row.get("synced")
            else "pending"
            if indexed
            else "unindexed",
        }

    def list_notes(self, vault_name, query="", status="", offset=0, limit=50):
        vault = self._vault(vault_name)
        if not isinstance(query, str) or len(query) > 200 or status not in ("", *STATUSES):
            raise ValueError("invalid filter")
        offset = max(0, min(int(offset), MAX_FILES))
        limit = max(1, min(int(limit), MAX_NAV_NOTES))
        rows, scanned, used, truncated = [], 0, 0, False
        chain = {".animus", ".animus/exported", ".animus/exported/Conhecimento"}
        for directory, dirs, files in os.walk(vault.path, followlinks=False):
            relative_dir = Path(directory).relative_to(vault.path)
            allowed_dirs = []
            for name in sorted(dirs):
                rel = (relative_dir / name).as_posix()
                if not _reparse(Path(directory) / name) and (
                    rel in chain or not self.collector._excluded(rel + "/placeholder.md")
                ):
                    allowed_dirs.append(name)
            dirs[:] = allowed_dirs
            for name in sorted(files):
                if not name.lower().endswith(".md"):
                    continue
                relative = (relative_dir / name).as_posix()
                if self.collector._excluded(relative):
                    continue
                scanned += 1
                if scanned > MAX_FILES or used > MAX_SCAN_BYTES:
                    truncated = True
                    break
                try:
                    path, raw, _, meta, body, warning = self._read(vault, relative)
                except (OSError, ValueError, UnicodeError, PermissionError):
                    continue
                used += len(raw)
                title, project = str(meta.get("title") or path.stem), str(meta.get("projeto") or "")
                current_status = str(meta.get("status") or "candidato")
                if status and status != current_status:
                    continue
                if (
                    query
                    and query.casefold() not in (title + "\n" + project + "\n" + body).casefold()
                ):
                    continue
                rows.append(
                    {
                        "vault": vault.name,
                        "path": relative,
                        "title": title,
                        "projeto": project,
                        "status": current_status,
                        "warning": bool(warning),
                        # The desktop graph is a bounded projection of canonical
                        # Obsidian links, not a second index or copied vault.
                        "links": [
                            link
                            for link in extract_links(body)
                            if len(link) <= 160
                        ][:4],
                    }
                )
            if truncated:
                break
        return {
            "notes": rows[offset : offset + limit],
            "total": len(rows),
            "offset": offset,
            "has_more": len(rows) > offset + limit,
            "truncated": truncated,
        }

    @staticmethod
    def _render(text, body, patch, newline):
        """Patch only selected scalar metadata; retain other YAML/comments verbatim."""
        lines = text.splitlines(keepends=True)
        end = (
            next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
            if text.startswith("---")
            else None
        )
        header = lines[1:end] if end is not None else []
        for key, value in patch.items():
            matches = [
                i
                for i, line in enumerate(header)
                if re.match(r"^" + re.escape(key) + r"\s*:", line)
            ]
            if len(matches) > 1:
                raise ValueError("duplicate metadata")
            if matches and re.match(r"^\s*[>|&*{\[]", header[matches[0]].split(":", 1)[1]):
                raise ValueError("complex metadata scalar")
            rendered = key + ": " + json.dumps(value, ensure_ascii=False) + newline
            if matches:
                i = matches[0]
                # Do not orphan a continuation block when editing a complex scalar.
                if i + 1 < len(header) and header[i + 1].startswith((" ", "\t")):
                    raise ValueError("multiline metadata scalar")
                header[i] = rendered
            else:
                header.append(rendered)
        normalized = body.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
        if end is None and not patch:
            return normalized
        return "---" + newline + "".join(header) + "---" + newline + normalized

    def save(
        self,
        vault_name,
        relative,
        expected_etag,
        body,
        patch=None,
        verified_ack=False,
        *,
        create=False,
    ):
        relative = relative.replace("\\", "/") if isinstance(relative, str) else relative
        vault = self._vault(vault_name, write=True)
        patch = patch or {}
        if not isinstance(patch, dict) or not set(patch).issubset(FIELDS):
            raise ValueError("unsupported metadata")
        if not isinstance(body, str) or not body.strip() or len(body.encode()) > MAX_NOTE_BYTES:
            raise ValueError("invalid note body")
        for value in patch.values():
            if not isinstance(value, str) or len(value) > 180 or any(ord(c) < 32 for c in value):
                raise ValueError("invalid metadata value")
        if "status" in patch and patch["status"] not in STATUSES:
            raise ValueError("invalid status")
        if "sensibilidade" in patch and patch["sensibilidade"] not in SENSITIVITIES:
            raise ValueError("invalid sensitivity")
        path = self._target(vault, relative)
        relative = path.relative_to(vault.path).as_posix()
        if not isinstance(expected_etag, str):
            raise TypeError("missing revision")
        with _edit_lock(self.config.data_dir, vault.name + "/" + relative):
            if create:
                if path.exists() or expected_etag:
                    raise KnowledgeConflict("note exists")
                raw, text, meta, old_body = b"", "", {}, ""
            else:
                _, raw, text, meta, old_body, warning = self._read(vault, relative)
                if warning:
                    raise ValueError("invalid frontmatter")
                if digest(raw) != expected_etag:
                    raise KnowledgeConflict("source changed")
            status = patch.get("status", meta.get("status", "candidato"))
            if (
                status == "verificado"
                and (body != old_body or meta.get("status") != status)
                and verified_ack is not True
            ):
                raise PermissionError("verification acknowledgment required")
            training = meta.get("treino", {})
            if (
                isinstance(training, dict)
                and training.get("aprovado") is True
                and (body != old_body or patch)
            ):
                raise PermissionError("training approval must be reviewed in the source")
            newline = "\r\n" if b"\r\n" in raw else "\n"
            metadata_patch = dict(patch)
            if "projeto" in patch:
                metadata_patch.update(projeto_manual=True, classificacao="manual")
            rendered = self._render(text, body, metadata_patch, newline)
            if _sensitive_findings(rendered):
                raise PermissionError("recognized secret")
            output = (
                b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
            ) + rendered.encode("utf-8")
            if len(output) > MAX_NOTE_BYTES:
                raise ValueError("note too large")
            for internal in (
                vault.path / ".animus",
                vault.path / ".animus/backups",
                vault.path / ".animus/audit.jsonl",
            ):
                if _reparse(internal):
                    raise PermissionError("unsafe audit path")
            if not create:
                if digest(path.read_bytes()) != expected_etag:
                    raise KnowledgeConflict("source changed")
                self.manager._backup(vault.path, Path(relative), path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if create:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(output)
                    stream.flush()
                    os.fsync(stream.fileno())
            else:
                if os.name == "nt":
                    with _windows_source(path) as stream:
                        actual = stream.read(MAX_NOTE_BYTES + 1)
                        if digest(actual) != expected_etag:
                            raise KnowledgeConflict("source changed")
                        # Hold the exclusive source handle through backup and flush.
                        # A crash retains the durable backup in the original vault.
                        backup = vault.path / self.manager._backup(vault.path, Path(relative), path)
                        with backup.open("r+b") as checkpoint:
                            os.fsync(checkpoint.fileno())
                        try:
                            stream.seek(0)
                            stream.write(output)
                            stream.truncate()
                            stream.flush()
                            os.fsync(stream.fileno())
                        except Exception:
                            stream.seek(0)
                            stream.write(actual)
                            stream.truncate()
                            stream.flush()
                            os.fsync(stream.fileno())
                            raise
                else:
                    if digest(path.read_bytes()) != expected_etag:
                        raise KnowledgeConflict("source changed")
                    _atomic_write(path, output.decode("utf-8"))
            self.manager._audit(
                vault.path,
                "desktop:owner",
                "explicit note edit",
                note_id(vault.name, relative),
                relative,
                "created" if create else "updated",
                raw.decode("utf-8"),
                output.decode("utf-8"),
                False,
            )
            indexed = True
            try:
                memory = memory_from_note(
                    self.config, vault, relative, output.decode("utf-8"), path.stat().st_mtime
                )
                self.engine.index_memory(memory)
            except (sqlite3.Error, OSError):
                indexed = False  # The canonical file is durable; normal collection will retry.
            self._request_sync()
        return {"saved": True, "indexed": indexed, "note": self.read(vault.name, relative)}

    def create(self, vault_name, title, body, project=""):
        if not isinstance(title, str) or not title.strip() or len(title) > 180:
            raise ValueError("invalid title")
        relative = "Conhecimento/" + sanitize_title(title) + ".md"
        return self.save(
            vault_name,
            relative,
            "",
            body,
            {
                "title": title.strip(),
                "projeto": project,
                "status": "candidato",
                "sensibilidade": "interno",
            },
            create=True,
        )

    def _request_sync(self):
        path = self.config.data_dir / "peer-command.json"
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write('{"action":"sync"}')
        except FileExistsError:
            pass  # Preserve another in-flight request.

    def refresh(self, vault_name):
        vault = self._vault(vault_name, write=True)
        rows = self.collector.collect_vault(vault)
        changed = self.engine.index_batch(rows)
        self.engine.mark_obsidian_missing(
            vault.name, self.config.node_id, self.collector.seen_by_vault.get(vault.name, set())
        )
        self._request_sync()
        return {"indexed": len(rows), "changed": changed}

    def synchronize(self):
        from .network.peer import AnimusPeer

        peer = AnimusPeer(self.config)
        try:
            sent = 0
            for _ in range(3):
                count = asyncio.run(peer.sync_to_hub())
                sent += count
                if count < 200:
                    break
            return {"sent": sent, **self.status()}
        finally:
            peer.engine.close()

    def dispatch(self, request):
        if not isinstance(request, dict):
            raise TypeError("invalid request")
        operation = request.get("op")
        if operation == "status":
            return self.status()
        if operation == "list":
            return self.list_notes(
                request.get("vault"),
                request.get("query", ""),
                request.get("status", ""),
                request.get("offset", 0),
                request.get("limit", 50),
            )
        if operation == "read":
            return self.read(request.get("vault"), request.get("path"))
        if operation == "resolve":
            return self.resolve(
                request.get("vault"), request.get("path", ""), request.get("reference")
            )
        if operation == "attachment":
            return self.attachment(
                request.get("vault"), request.get("path", ""), request.get("reference")
            )
        if operation == "save":
            return self.save(
                request.get("vault"),
                request.get("path"),
                request.get("etag"),
                request.get("body"),
                request.get("patch"),
                request.get("verified_ack", False),
            )
        if operation == "create":
            return self.create(
                request.get("vault"),
                request.get("title"),
                request.get("body"),
                request.get("projeto", ""),
            )
        if operation == "refresh":
            return self.refresh(request.get("vault"))
        if operation == "sync":
            return self.synchronize()
        raise ValueError("unknown operation")


def main():
    engine = None
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("request too large")
        request = json.loads(raw)
        config = AnimusConfig.load()
        engine = IndexEngine(config.db_path)
        result = {"ok": True, "data": KnowledgeService(config, engine).dispatch(request)}
    except KnowledgeConflict as error:
        message = (
            "Já existe uma nota com esse título. Escolha outro título."
            if str(error) == "note exists"
            else "A nota mudou desde a abertura. Recarregue antes de salvar."
        )
        result = {"ok": False, "code": "conflict", "message": message}
    except PermissionError:
        result = {
            "ok": False,
            "code": "permission",
            "message": "Ação não permitida. Confira o vault, a confirmação de verificação e o conteúdo sensível.",
        }
    except (ValueError, TypeError, UnicodeError):
        result = {
            "ok": False,
            "code": "invalid",
            "message": "Dados inválidos ou metadados complexos. Revise a nota e tente novamente.",
        }
    except (OSError, sqlite3.Error):
        result = {
            "ok": False,
            "code": "unavailable",
            "message": "Conhecimento indisponível. Confira o vault e o peer.",
        }
    finally:
        if engine is not None:
            engine.close()
    sys.stdout.write(json.dumps(result, ensure_ascii=True, default=str) + "\n")


if __name__ == "__main__":
    main()
