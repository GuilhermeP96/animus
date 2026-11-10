"""Per-instance, reference-counted MCP activity. No tool names or arguments."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading
import time
import uuid

from ..network.status import utc_now


class MCPActivity:
    HOLD_SECONDS = 4

    def __init__(self, data_dir: Path):
        self.folder = data_dir / 'mcp-activity'
        self.instance = uuid.uuid4().hex
        self.path = self.folder / f'{os.getpid()}-{self.instance}.json'
        self.lock = threading.RLock()
        self.done = threading.Event()
        self.worker = None
        self.active = 0
        self.completed = 0.0
        self.enabled = not self.folder.is_symlink()

    def _write(self):
        if not self.enabled:
            return
        try:
            if self.folder.is_symlink():
                return
            self.folder.mkdir(mode=0o700, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            if temporary.is_symlink() or self.path.is_symlink():
                return
            fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY |
                         getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as out:
                json.dump(dict(schema=1, pid=os.getpid(), instance=self.instance,
                               active_calls=self.active, heartbeat=utc_now()), out)
            os.replace(temporary, self.path)
        except OSError:
            pass

    def _remove(self):
        try:
            if self.path.is_symlink() or self.path.stat().st_size > 512:
                return
            payload = json.loads(self.path.read_text(encoding='utf-8'))
            if payload.get('instance') == self.instance and payload.get('pid') == os.getpid():
                self.path.unlink()
        except (OSError, ValueError):
            pass

    def _heartbeat(self):
        while not self.done.wait(1):
            with self.lock:
                if not self.active and time.monotonic() - self.completed >= self.HOLD_SECONDS:
                    self._remove()
                    self.worker = None
                    return
                self._write()

    @contextmanager
    def track(self):
        with self.lock:
            self.active += 1
            self._write()
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._heartbeat, daemon=True,
                                               name='animus-mcp-activity')
                self.worker.start()
        try:
            yield
        finally:
            with self.lock:
                self.active = max(0, self.active - 1)
                self.completed = time.monotonic()
                self._write()

    def close(self):
        self.done.set()
        if self.worker:
            self.worker.join(timeout=2)
        with self.lock:
            self._remove()
