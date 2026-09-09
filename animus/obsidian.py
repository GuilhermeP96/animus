"""Safe export and agent-organization layer for Obsidian vaults."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from .collector.obsidian import parse_frontmatter
from .config import AnimusConfig, ObsidianVaultConfig
from .indexer.engine import IndexEngine


@dataclass
class ExportResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sanitize_title(title: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", title).strip(" .-")
    value = re.sub(r"\s+", " ", value)
    return value[:100].rstrip() or "memory"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _yaml_frontmatter(data: dict[str, Any]) -> str:
    dumped = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{dumped}\n---\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def initialize_vault(vault: ObsidianVaultConfig) -> None:
    """Create the managed layout and non-authoritative vault metadata."""
    root = vault.path.expanduser().resolve()
    managed = root / ".animus"
    for child in ("exported", "quarantine", "backups"):
        (managed / child).mkdir(parents=True, exist_ok=True)
    metadata = managed / "config.json"
    if not metadata.exists():
        _atomic_write(
            metadata,
            json.dumps(
                {
                    "vault": vault.name,
                    "managed_path": ".animus/exported",
                    "note": "Effective configuration remains in the Animus peer data directory.",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
    readme = managed / "README.md"
    if not readme.exists():
        _atomic_write(
            readme,
            "# Animus managed area\n\n"
            "Files in `exported/` are managed by Animus. Conflicting generated notes "
            "are preserved in `quarantine/`; recoverable snapshots live in `backups/`; "
            "actions are recorded in `audit.jsonl`. Human notes outside this directory "
            "are never overwritten by the integration.\n",
        )


class ObsidianManager:
    """Enforce managed-folder, conflict, audit, backup, and rollback rules."""

    def __init__(self, config: AnimusConfig, engine: IndexEngine):
        self.config = config
        self.engine = engine

    def vault(self, name: str) -> ObsidianVaultConfig:
        for vault in self.config.obsidian_vaults:
            if vault.name == name:
                root = vault.path.expanduser().resolve()
                if not root.is_dir():
                    raise ValueError(f"vault path is unavailable: {root}")
                return vault.model_copy(update={"path": root})
        raise ValueError(f"unknown Obsidian vault: {name}")

    def export(
        self,
        vault_name: str,
        memory_ids: Iterable[str],
        *,
        dry_run: bool = False,
        actor: str = "cli",
        reason: str = "explicit export",
        destination_folder: str = ".animus/exported",
    ) -> ExportResult:
        vault = self.vault(vault_name)
        if not vault.export_enabled:
            raise PermissionError(f"export is disabled for vault '{vault.name}'")
        result = ExportResult(dry_run=dry_run)
        root = vault.path
        folder = Path(destination_folder.replace("\\", "/"))
        managed_root = (root / ".animus" / "exported").resolve()
        destination_root = (root / folder).resolve()
        if (
            folder.is_absolute()
            or ".." in folder.parts
            or (destination_root != managed_root and managed_root not in destination_root.parents)
        ):
            raise PermissionError("export destination must be inside .animus/exported")
        for memory_id in dict.fromkeys(memory_ids):
            row = self.engine.get_memory(memory_id)
            if not row:
                result.skipped.append(memory_id)
                continue
            relative = (
                folder / f"{sanitize_title(row.get('title') or 'memory')}--{memory_id[:8]}.md"
            )
            target = root / relative
            # A title can evolve while the memory identity stays stable.
            # Locate an earlier managed export by ID suffix so an edit does
            # not leave duplicate notes under the old and new titles.
            export_root = root / ".animus" / "exported"
            if export_root.is_dir():
                for candidate in export_root.rglob(f"*--{memory_id[:8]}.md"):
                    try:
                        candidate_meta, _, candidate_warning = parse_frontmatter(
                            candidate.read_text(encoding="utf-8")
                        )
                    except (OSError, UnicodeError):
                        continue
                    marker = candidate_meta.get("animus", {})
                    if (
                        not candidate_warning
                        and isinstance(marker, dict)
                        and marker.get("memory_id") == memory_id
                        and marker.get("managed") is True
                    ):
                        target = candidate
                        relative = candidate.relative_to(root)
                        break
            body = (row.get("content") or "").strip() + "\n"
            body_hash = _hash(body)
            frontmatter = {
                "animus": {
                    "memory_id": memory_id,
                    "source_type": row.get("type", ""),
                    "source_node": row.get("source_node", ""),
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "managed": True,
                    "content_hash": body_hash,
                }
            }
            rendered = _yaml_frontmatter(frontmatter) + "\n" + body
            action = "created"
            before = ""
            if target.exists():
                before = target.read_text(encoding="utf-8")
                existing_meta, existing_body, warning = parse_frontmatter(before)
                marker = existing_meta.get("animus", {}) if isinstance(existing_meta, dict) else {}
                if (
                    warning
                    or not isinstance(marker, dict)
                    or marker.get("managed") is not True
                    or marker.get("memory_id") != memory_id
                ):
                    conflict = self._quarantine(root, relative, rendered, memory_id, dry_run)
                    result.conflicts.append(str(conflict))
                    self._audit(
                        root,
                        actor,
                        reason,
                        memory_id,
                        str(relative),
                        "conflict",
                        before,
                        rendered,
                        dry_run,
                    )
                    continue
                recorded_hash = marker.get("content_hash")
                current_hash = _hash(existing_body.lstrip("\r\n").rstrip() + "\n")
                if recorded_hash and current_hash != recorded_hash:
                    conflict = self._quarantine(root, relative, rendered, memory_id, dry_run)
                    result.conflicts.append(str(conflict))
                    self._audit(
                        root,
                        actor,
                        reason,
                        memory_id,
                        str(relative),
                        "conflict",
                        before,
                        rendered,
                        dry_run,
                    )
                    continue
                if current_hash == body_hash:
                    result.unchanged.append(str(relative))
                    continue
                # Keep user/agent-added frontmatter (tags, aliases, project,
                # etc.) while replacing only Animus' authoritative marker.
                frontmatter = {**existing_meta, "animus": frontmatter["animus"]}
                rendered = _yaml_frontmatter(frontmatter) + "\n" + body
                action = "updated"
            if not dry_run:
                if before:
                    self._backup(root, relative, target)
                _atomic_write(target, rendered)
            getattr(result, action).append(str(relative))
            self._audit(
                root, actor, reason, memory_id, str(relative), action, before, rendered, dry_run
            )
        return result

    def build_catalog(self, vault_name: str, *, actor: str = "curator") -> dict[str, Any]:
        """Create a navigable Obsidian index over all managed exports."""
        vault = self.vault(vault_name)
        root = vault.path
        export_root = root / ".animus" / "exported"
        groups: dict[str, list[tuple[str, str, str]]] = {}
        for note in export_root.rglob("*.md"):
            if note.name == "00 - Indice Animus.md":
                continue
            try:
                metadata, _, warning = parse_frontmatter(note.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
            marker = metadata.get("animus", {}) if isinstance(metadata, dict) else {}
            memory_id = marker.get("memory_id") if isinstance(marker, dict) else None
            if warning or not memory_id:
                continue
            row = self.engine.get_memory(str(memory_id))
            if not row:
                continue
            group = row.get("type") or "other"
            relative = note.relative_to(root).with_suffix("").as_posix()
            groups.setdefault(group, []).append(
                (row.get("workspace") or "sem-workspace", row.get("title") or note.stem, relative)
            )
        lines = [
            "# Indice de Memorias Animus",
            "",
            "> Conhecimento curado exportado do indice Animus. Conversas brutas permanecem no MCP.",
            "",
            f"Atualizado em: {datetime.now(timezone.utc).isoformat()}",
            "",
        ]
        count = 0
        for group, entries in sorted(groups.items()):
            lines.extend((f"## {group}", ""))
            current_workspace = None
            for workspace, title, relative in sorted(entries, key=lambda item: (item[0], item[1])):
                if workspace != current_workspace:
                    lines.extend((f"### {workspace}", ""))
                    current_workspace = workspace
                lines.append(f"- [[{relative}|{title}]]")
                count += 1
            lines.append("")
        body = "\n".join(lines).rstrip() + "\n"
        frontmatter = {
            "tags": ["animus", "indice", "memorias-curadas"],
            "animus": {
                "managed": True,
                "artifact": "catalog",
                "content_hash": _hash(body),
            },
        }
        target = export_root / "00 - Indice Animus.md"
        before = target.read_text(encoding="utf-8") if target.exists() else ""
        rendered = _yaml_frontmatter(frontmatter) + "\n" + body
        if before and before != rendered:
            self._backup(root, target.relative_to(root), target)
        if before != rendered:
            _atomic_write(target, rendered)
            self._audit(
                root,
                actor,
                "rebuild curated catalog",
                "catalog",
                target.relative_to(root).as_posix(),
                "updated" if before else "created",
                before,
                rendered,
                False,
            )
        return {"path": target.relative_to(root).as_posix(), "notes": count}

    def quarantine_exports(
        self, vault_name: str, memory_ids: Iterable[str], *, reason: str, actor: str = "curator"
    ) -> list[str]:
        """Move managed exports out of the knowledge graph without deleting them."""
        vault = self.vault(vault_name)
        root = vault.path
        moved: list[str] = []
        for memory_id in dict.fromkeys(memory_ids):
            for source in (root / ".animus" / "exported").rglob(f"*--{memory_id[:8]}.md"):
                metadata, _, warning = parse_frontmatter(source.read_text(encoding="utf-8"))
                marker = metadata.get("animus", {}) if isinstance(metadata, dict) else {}
                if warning or not isinstance(marker, dict) or marker.get("memory_id") != memory_id:
                    continue
                destination = root / ".animus" / "quarantine" / "curadoria" / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    destination = destination.with_name(
                        f"{destination.stem}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                        f"{destination.suffix}"
                    )
                before = source.read_text(encoding="utf-8")
                os.replace(source, destination)
                relative = destination.relative_to(root).as_posix()
                moved.append(relative)
                self._audit(
                    root, actor, reason, memory_id, relative, "quarantined", before, before, False
                )
                break
        return moved

    def propose_organization(
        self,
        vault_name: str,
        memory_ids: Iterable[str],
        *,
        folder: str = ".animus/exported",
        actor: str = "agent",
        reason: str = "organize memories",
    ) -> dict[str, Any]:
        vault = self.vault(vault_name)
        normalized = Path(folder.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("folder must be a relative path inside the vault")
        managed = normalized.parts[:2] == (".animus", "exported")
        operations = []
        for memory_id in dict.fromkeys(memory_ids):
            row = self.engine.get_memory(memory_id)
            if not row:
                continue
            destination = (
                normalized / f"{sanitize_title(row.get('title') or 'memory')}--{memory_id[:8]}.md"
            )
            operations.append(
                {
                    "operation": "export",
                    "memory_id": memory_id,
                    "source": row.get("source_path") or f"animus://memory/{memory_id}",
                    "destination": destination.as_posix(),
                    "reason": reason,
                    "risk": "low" if managed else "protected",
                }
            )
        request_raw = json.dumps([vault.name, actor, reason, operations], sort_keys=True)
        return {
            "request_id": hashlib.sha256(request_raw.encode()).hexdigest()[:16],
            "mode": "propose",
            "vault": vault.name,
            "actor": actor,
            "managed_scope": managed,
            "operations": operations,
        }

    def apply_organization(
        self, proposal: dict[str, Any], *, approved: bool, dry_run: bool = False
    ) -> ExportResult:
        if not approved:
            raise PermissionError("organization apply requires explicit approval")
        if not proposal.get("managed_scope"):
            raise PermissionError("organization can only write inside .animus/exported")
        ids = [
            op["memory_id"]
            for op in proposal.get("operations", [])
            if op.get("operation") == "export"
        ]
        return self.export(
            proposal["vault"],
            ids,
            dry_run=dry_run,
            actor=proposal.get("actor", "agent"),
            reason=f"organization {proposal.get('request_id', '')}",
        )

    def rollback_last(self, vault_name: str) -> str:
        vault = self.vault(vault_name)
        audit_path = vault.path / ".animus" / "audit.jsonl"
        if not audit_path.exists():
            raise ValueError("no audit log found")
        records = [
            json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line
        ]
        record = next(
            (r for r in reversed(records) if r.get("backup") or r.get("action") == "created"), None
        )
        if not record:
            raise ValueError("no recoverable operation found")
        target = (vault.path / record["path"]).resolve()
        if vault.path not in target.parents or not target.is_file():
            raise ValueError("invalid or missing rollback target")
        if record.get("action") == "created":
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            archived = vault.path / ".animus" / "backups" / stamp / record["path"]
            archived.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, archived)
        else:
            backup = (vault.path / record["backup"]).resolve()
            if vault.path not in backup.parents or not backup.is_file():
                raise ValueError("invalid or missing backup")
            _atomic_write(target, backup.read_text(encoding="utf-8"))
        self._audit(
            vault.path,
            "cli",
            "rollback",
            record["memory_id"],
            record["path"],
            "rollback",
            "",
            "",
            False,
        )
        return record["path"]

    def _quarantine(
        self, root: Path, relative: Path, rendered: str, memory_id: str, dry_run: bool
    ) -> Path:
        target = root / ".animus" / "quarantine" / f"{relative.stem}--conflict-{memory_id[:8]}.md"
        if target.exists():
            target = target.with_name(
                f"{target.stem}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.md"
            )
        if not dry_run:
            _atomic_write(target, rendered)
        return target.relative_to(root)

    def _backup(self, root: Path, relative: Path, target: Path) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = root / ".animus" / "backups" / stamp / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        return backup.relative_to(root).as_posix()

    def _audit(
        self,
        root: Path,
        actor: str,
        reason: str,
        memory_id: str,
        path: str,
        action: str,
        before: str,
        after: str,
        dry_run: bool,
    ) -> None:
        if dry_run:
            return
        backup = ""
        if before and action == "updated":
            # The actual backup is already present; resolve the newest matching one.
            candidates = list((root / ".animus" / "backups").glob(f"*/{path}"))
            if candidates:
                backup = (
                    max(candidates, key=lambda p: p.stat().st_mtime).relative_to(root).as_posix()
                )
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "reason": reason,
            "memory_id": memory_id,
            "path": path,
            "action": action,
            "before_hash": _hash(before) if before else "",
            "after_hash": _hash(after) if after else "",
            "backup": backup,
        }
        audit = root / ".animus" / "audit.jsonl"
        audit.parent.mkdir(parents=True, exist_ok=True)
        with audit.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
