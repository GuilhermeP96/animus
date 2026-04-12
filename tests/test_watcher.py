"""Tests for animus.collector.watcher — MemoryWatcher."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from watchdog.events import FileCreatedEvent, FileModifiedEvent

from animus.collector.watcher import MemoryWatcher
from animus.config import AnimusConfig


@pytest.fixture
def watcher(config):
    callback = MagicMock()
    w = MemoryWatcher(config, on_change=callback)
    return w, callback


class TestPatternMatching:
    def test_matching_pattern_triggers_callback(self, watcher):
        w, cb = watcher
        event = FileCreatedEvent(str(Path("/some/debug-logs/test.jsonl")))
        w.on_created(event)
        cb.assert_called_once()

    def test_non_matching_pattern_no_callback(self, watcher):
        w, cb = watcher
        event = FileCreatedEvent(str(Path("/random/file.txt")))
        w.on_created(event)
        cb.assert_not_called()

    def test_modified_event_triggers(self, watcher):
        w, cb = watcher
        event = FileModifiedEvent(str(Path("/ws/copilot-chat/conv.json")))
        w.on_modified(event)
        cb.assert_called_once()

    def test_directory_events_ignored(self, watcher):
        w, cb = watcher
        event = FileCreatedEvent(str(Path("/some/debug-logs/")))
        event._is_directory = True  # watchdog attr
        # The handler checks event.is_directory
        # Simulate directory event
        class DirEvent:
            is_directory = True
            src_path = str(Path("/some/debug-logs/"))
        w.on_created(DirEvent())
        cb.assert_not_called()

    def test_instructions_md_matches(self, watcher):
        w, cb = watcher
        event = FileCreatedEvent(str(Path("/proj/.instructions.md")))
        w.on_created(event)
        cb.assert_called_once()

    def test_prompt_md_matches(self, watcher):
        w, cb = watcher
        event = FileCreatedEvent(str(Path("/proj/.github/prompts/test.prompt.md")))
        w.on_created(event)
        cb.assert_called_once()


class TestCallbackError:
    def test_callback_error_is_caught(self, watcher):
        w, cb = watcher
        cb.side_effect = ValueError("boom")
        event = FileCreatedEvent(str(Path("/some/debug-logs/test.log")))
        # Should not raise
        w.on_created(event)


class TestStartStop:
    def test_start_nonexistent_dir(self, config):
        config.vscode_user_dir = Path("/nonexistent/path/xyz")
        cb = MagicMock()
        w = MemoryWatcher(config, on_change=cb)
        # start() only schedules if dir exists, so no error expected
        w.start()
        # stop/join may raise if observer never started — that's fine
        try:
            w.stop()
        except RuntimeError:
            pass
