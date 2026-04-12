"""File watcher — live collection of new memories as they appear."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable

from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from ..config import AnimusConfig

logger = logging.getLogger("animus.watcher")


class MemoryWatcher(FileSystemEventHandler):
    """Watches for new/modified Copilot interaction files."""

    WATCH_PATTERNS = {
        "debug-logs",
        "copilot-chat",
        ".instructions.md",
        "copilot-instructions.md",
        ".prompt.md",
        ".agent.md",
    }

    def __init__(self, config: AnimusConfig, on_change: Callable[[Path], None]):
        self.config = config
        self.on_change = on_change
        self._observer = Observer()

    def on_created(self, event: FileCreatedEvent) -> None:
        if not event.is_directory:
            self._handle(Path(event.src_path))

    def on_modified(self, event: FileModifiedEvent) -> None:
        if not event.is_directory:
            self._handle(Path(event.src_path))

    def _handle(self, path: Path) -> None:
        path_str = str(path)
        if any(pat in path_str for pat in self.WATCH_PATTERNS):
            logger.info("Memory change detected: %s", path)
            try:
                self.on_change(path)
            except Exception as e:
                logger.error("Error processing %s: %s", path, e)

    def start(self) -> None:
        watch_dir = self.config.vscode_user_dir
        if watch_dir.exists():
            self._observer.schedule(self, str(watch_dir), recursive=True)
            self._observer.start()
            logger.info("Watcher started on %s", watch_dir)

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
