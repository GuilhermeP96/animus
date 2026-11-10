"""Private, bounded local IPC for the desktop; never serialize configuration."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class PeerStatus:
    def __init__(self, data_dir: Path, interval: int):
        self.path = data_dir / "peer-status.json"
        self.command = data_dir / "peer-command.json"
        self.lock = threading.RLock()
        self.done = threading.Event()
        self.thread = None
        self.data = dict(schema=1, version=__version__, pid=os.getpid(),
                         phase="starting", connected=False, connection_status="unknown", last_success=None,
                         last_cycle=None, interval_seconds=interval, total_memories=None,
                         unsynced=None, workspaces=None, stats_status="unavailable", events=[])

    def update(self, **values):
        with self.lock:
            self.data.update(values)

    def event(self, code: str):
        # Callers pass fixed codes only; never pass exception/HTTP response text.
        if code not in {"collect", "push_ok", "pull_ok", "hub_unavailable",
                        "cycle_error", "cycle_complete", "starting", "stopped"}:
            return
        with self.lock:
            self.data["events"] = ([dict(code=code, at=utc_now())] + self.data["events"])[:10]

    def connection(self, success: bool):
        self.update(connected=success, connection_status="connected" if success else "disconnected",
                    **({"last_success": utc_now()} if success else {}))
        if not success:
            self.event("hub_unavailable")

    def snapshot(self):
        with self.lock:
            return {**self.data, "heartbeat": utc_now()}

    def write(self):
        temporary = self.path.with_suffix(".tmp")
        try:
            # A private parent directory is established by AnimusConfig.ensure_dirs.
            # Refuse links instead of following an unexpected operator-created file.
            if self.path.is_symlink() or temporary.is_symlink():
                return
            flags = os.O_CREAT | os.O_TRUNC | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(temporary, flags, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.snapshot(), stream, ensure_ascii=True)
            os.replace(temporary, self.path)
        except OSError:
            # Desktop telemetry must not interrupt collection or authenticated sync.
            pass

    def start(self):
        self.event("starting")
        self.write()
        def heartbeat():
            while not self.done.wait(3):
                self.write()
        self.thread = threading.Thread(target=heartbeat, daemon=True, name="animus-status")
        self.thread.start()

    def stop(self):
        self.done.set()
        if self.thread:
            self.thread.join(timeout=4)
        self.update(phase="stopped", connected=False, connection_status="disconnected")
        self.event("stopped")
        self.write()

    def sync_requested(self):
        try:
            if self.command.is_symlink() or self.command.stat().st_size > 512:
                return False
            age = time.time() - self.command.stat().st_mtime
            data = json.loads(self.command.read_text(encoding="utf-8"))
            self.command.unlink()
            return 0 <= age < 90 and data == {"action": "sync"}
        except (OSError, ValueError):
            return False
