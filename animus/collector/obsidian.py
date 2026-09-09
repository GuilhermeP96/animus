"""Opt-in Obsidian vault collector.

Notes keep a stable identity based on ``vault + relative_path``. Their body
hash lives in metadata, allowing the index to update a note in place without
creating a new search result on every edit.
"""

from __future__ import annotations

import fnmatch
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

import yaml

from ..config import AnimusConfig, ObsidianVaultConfig
from .models import Memory, MemoryType

logger = logging.getLogger("animus.collector.obsidian")
_WIKI_LINK = re.compile(r"(?<!\!)\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
_MD_LINK = re.compile(r"(?<!\!)\[[^\]]+\]\((?!https?://|mailto:)([^) #]+)(?:#[^)]+)?\)")
_INLINE_TAG = re.compile(r"(?<![\w/])#([\w][\w/-]*)", re.UNICODE)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str, str | None]:
    """Return (frontmatter, body, diagnostic), tolerating malformed YAML."""
    if not text.startswith("---"):
        return {}, text, None
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text, None
    end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        return {}, text, "frontmatter is not closed"
    raw = "".join(lines[1:end])
    body = "".join(lines[end + 1 :])
    try:
        value = yaml.safe_load(raw) or {}
        if not isinstance(value, dict):
            return {}, body, "frontmatter root must be a mapping"
        return value, body, None
    except yaml.YAMLError as exc:
        return {}, body, f"invalid YAML frontmatter: {exc.__class__.__name__}"


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip().lstrip("#") for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(part).strip().lstrip("#") for part in value if str(part).strip()]
    return []


def extract_links(text: str) -> list[str]:
    links = [match.strip() for match in _WIKI_LINK.findall(text)]
    links.extend(match.strip() for match in _MD_LINK.findall(text))
    return list(dict.fromkeys(link for link in links if link))


def note_id(vault: str, relative_path: str) -> str:
    raw = f"obsidian:{vault}:{relative_path.replace(chr(92), '/')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class ObsidianCollector:
    """Collect Markdown notes from all enabled local vaults."""

    def __init__(self, config: AnimusConfig):
        self.config = config
        self.diagnostics: list[dict[str, str]] = []
        self.seen_by_vault: dict[str, set[str]] = {}

    def collect_all(self) -> list[Memory]:
        self.diagnostics = []
        self.seen_by_vault = {}
        if not self.config.collect_obsidian:
            return []
        memories: list[Memory] = []
        for vault in self.config.obsidian_vaults:
            if not vault.enabled:
                continue
            try:
                memories.extend(self.collect_vault(vault))
            except OSError as exc:
                self._diagnostic(vault.name, "", f"vault unavailable: {exc}")
        return memories

    def collect_vault(self, vault: ObsidianVaultConfig) -> list[Memory]:
        root = vault.path.expanduser().resolve()
        if not root.is_dir():
            self._diagnostic(vault.name, "", "vault path does not exist or is not a directory")
            return []
        memories: list[Memory] = []
        seen: set[str] = set()
        self.seen_by_vault[vault.name] = seen
        for path in root.rglob("*.md"):
            relative = path.relative_to(root).as_posix()
            if self._excluded(relative):
                continue
            try:
                raw = path.read_text(encoding="utf-8")
                frontmatter, body, warning = parse_frontmatter(raw)
                if warning:
                    self._diagnostic(vault.name, relative, warning)
                digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                animus_meta = frontmatter.get("animus", {})
                if not isinstance(animus_meta, dict):
                    animus_meta = {}
                frontmatter_tags = _string_list(frontmatter.get("tags"))
                tags = list(dict.fromkeys(frontmatter_tags + _INLINE_TAG.findall(body)))
                links = extract_links(body)
                memory_id = note_id(vault.name, relative)
                seen.add(memory_id)
                stat = path.stat()
                memories.append(
                    Memory(
                        id=memory_id,
                        type=MemoryType.OBSIDIAN_NOTE,
                        source_node=self.config.node_id,
                        source_path=f"obsidian://{vault.name}/{relative}",
                        workspace=str(frontmatter.get("workspace") or vault.name),
                        timestamp=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                        title=str(frontmatter.get("title") or path.stem),
                        content=raw,
                        tags=tags,
                        metadata={
                            "source": "obsidian",
                            "vault": vault.name,
                            "relative_path": relative,
                            "frontmatter": frontmatter,
                            "frontmatter_tags": frontmatter_tags,
                            "obsidian_links": links,
                            "exported_by_animus": bool(animus_meta.get("managed")),
                            "content_hash": digest,
                            "missing": False,
                        },
                    )
                )
            except (OSError, UnicodeError) as exc:
                self._diagnostic(vault.name, relative, f"could not read note: {exc}")
        return memories

    def _excluded(self, relative: str) -> bool:
        normalized = relative.replace("\\", "/")
        return any(
            fnmatch.fnmatch(normalized, pattern)
            or (pattern.endswith("/**") and normalized.startswith(pattern[:-3].rstrip("/") + "/"))
            for pattern in self.config.obsidian_exclude_patterns
        )

    def _diagnostic(self, vault: str, path: str, message: str) -> None:
        self.diagnostics.append({"vault": vault, "relative_path": path, "message": message})
        logger.warning("Obsidian vault=%s note=%s: %s", vault, path or "-", message)
