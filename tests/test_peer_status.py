import json
import os
import time

from animus.network.status import PeerStatus


def test_local_status_has_no_configuration_or_memory_payload(tmp_path):
    status = PeerStatus(tmp_path, 300)
    status.start()
    try:
        status.connection(True)
        status.event('private-path-and-secret')
        status.update(phase='idle', total_memories=23)
        status.write()
        data = json.loads(status.path.read_text())
        assert data['connected'] and data['last_success']
        assert data['total_memories'] == 23
        assert not {'hub_url', 'server_secret', 'config', 'content', 'node_id'} & data.keys()
        assert 'private-path' not in status.path.read_text()
        if os.name != 'nt':
            assert status.path.stat().st_mode & 0o777 == 0o600
    finally:
        status.stop()
    assert json.loads(status.path.read_text())['phase'] == 'stopped'


def test_sync_command_is_bounded_one_shot_and_expires(tmp_path):
    status = PeerStatus(tmp_path, 300)
    status.command.write_text('{"action":"sync"}')
    assert status.sync_requested()
    assert not status.sync_requested()
    status.command.write_text('{"action":"collect","hub_url":"http://example.invalid"}')
    assert not status.sync_requested()
    status.command.write_text('{"action":"sync"}')
    os.utime(status.command, (time.time()-100, time.time()-100))
    assert not status.sync_requested()
    status.command.write_text('x'*513)
    assert not status.sync_requested()


def test_status_never_follows_symlinks(tmp_path):
    if os.name == 'nt':
        return
    target = tmp_path/'unrelated'; target.write_text('preserve')
    status = PeerStatus(tmp_path, 300)
    status.path.symlink_to(target)
    status.write()
    assert target.read_text() == 'preserve'
    status.command.symlink_to(target)
    assert not status.sync_requested()


def test_disconnection_retains_last_success_and_bounded_events(tmp_path):
    status = PeerStatus(tmp_path, 300)
    status.connection(True)
    before = status.snapshot()['last_success']
    status.connection(False)
    for _ in range(30):
        status.event('collect')
    data = status.snapshot()
    assert not data['connected'] and data['last_success'] == before
    assert len(data['events']) == 10
