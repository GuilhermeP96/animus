import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from animus.mcp.activity import MCPActivity


def test_nested_and_parallel_calls_never_clear_each_other(tmp_path):
    tracker = MCPActivity(tmp_path)
    barrier = threading.Barrier(3)
    release = threading.Event()
    def call():
        with tracker.track():
            barrier.wait(timeout=5)
            release.wait(timeout=5)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(call) for _ in range(2)]
            barrier.wait(timeout=5)
            assert json.loads(tracker.path.read_text())['active_calls'] == 2
            with tracker.track():
                assert json.loads(tracker.path.read_text())['active_calls'] == 3
            assert json.loads(tracker.path.read_text())['active_calls'] == 2
            release.set()
            for future in futures:
                future.result(timeout=5)
        assert json.loads(tracker.path.read_text())['active_calls'] == 0
    finally:
        release.set()
        tracker.close()
    assert not tracker.path.exists()


def test_instances_have_independent_files_and_exception_cleanup(tmp_path):
    first, second = MCPActivity(tmp_path), MCPActivity(tmp_path)
    try:
        with first.track():
            with pytest.raises(RuntimeError):
                with second.track():
                    assert first.path != second.path
                    assert json.loads(first.path.read_text())['active_calls'] == 1
                    raise RuntimeError('private-query-must-not-be-published')
            assert json.loads(first.path.read_text())['active_calls'] == 1
            assert json.loads(second.path.read_text())['active_calls'] == 0
        payload = json.loads(first.path.read_text())
        assert set(payload) == {'schema', 'pid', 'instance', 'active_calls', 'heartbeat'}
        assert 'private-query' not in first.path.read_text()
    finally:
        first.close()
        second.close()


def test_closed_client_cannot_remove_another_clients_activity(tmp_path):
    first, second = MCPActivity(tmp_path), MCPActivity(tmp_path)
    try:
        with second.track():
            first.close()
            assert second.path.is_file()
    finally:
        second.close()
