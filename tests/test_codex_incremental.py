"""Synthetic regression fixtures; never read the developer's Codex profile."""
import json
import sqlite3
from pathlib import Path

import pytest
from test_codex_collector import message, session

from animus.collector import codex
from animus.collector.codex import CodexCollector
from animus.collector.models import MemoryType


def checkpoint(collector, engine):
    rows = collector.collect_all()
    engine.index_batch(rows)
    collector.acknowledge()
    return rows


def summary(config, store, cwd, body='Validated migration with retained backups.', name='run'):
    path = config.codex_data_dir / store / 'rollout_summaries' / f'{name}.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'thread_id: owned-fixture\nupdated_at: 2026-11-11T10:00:00Z\n'
                    f'rollout_path: unused\ncwd: {cwd}\n\n{body}\n', encoding='utf-8')
    return path


def history(config, cwd, *, source='vscode'):
    root = config.codex_data_dir
    root.mkdir(parents=True, exist_ok=True)
    state = sqlite3.connect(root / 'state_5.sqlite')
    state.execute('CREATE TABLE threads (id TEXT, cwd TEXT, rollout_path TEXT, source TEXT)')
    state.execute('INSERT INTO threads VALUES (?,?,?,?)', ('owned-fixture', str(cwd), '', source))
    state.commit()
    state.close()
    db = sqlite3.connect(root / 'thread_history_1.sqlite')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('''CREATE TABLE thread_items (thread_id TEXT, rollout_ordinal INTEGER,
        updated_at_ordinal INTEGER, created_at_ms INTEGER, item_type TEXT, item_json TEXT)''')
    db.execute('CREATE INDEX history_page ON thread_items(thread_id,updated_at_ordinal)')
    return db


def add_item(db, ordinal, item, updated=None):
    db.execute('INSERT INTO thread_items VALUES (?,?,?,?,?,?)', ('owned-fixture', ordinal,
        ordinal if updated is None else updated, 1794391200000, item['type'], json.dumps(item)))
    db.commit()


def test_ack_only_after_index_and_restart_resume(config, tmp_path, engine):
    file = session(config, tmp_path, [message('user', text='First request')])
    collector = CodexCollector(config)
    first = collector.collect_all()
    assert not collector.checkpoint_path.exists()
    assert [m.id for m in collector.collect_all()] == [m.id for m in first]
    checkpoint(collector, engine)
    assert CodexCollector(config).collect_all() == []
    with file.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(message(text='Second response')) + '\n')
    resumed = checkpoint(CodexCollector(config), engine)
    assert [m.content for m in resumed] == ['Second response']


def test_windows_extended_paths_and_boundary(config):
    config.codex_allowed_workspaces = [Path('C:/repo')]
    c = CodexCollector(config)
    assert c._allowed('\\\\?\\C:\\repo\\animus')
    assert c._allowed('c:\\REPO')
    assert not c._allowed('C:/repo-private')
    assert not c._allowed('C:/repo/../private')
    assert not c._allowed('C:/repo/\x00')
    config.codex_allowed_workspaces = [Path('//server/share/repo')]
    assert c._allowed('\\\\?\\UNC\\server\\share\\repo\\project')


def test_large_records_progress_partial_append_and_fairness(config, tmp_path, engine, monkeypatch):
    file = session(config, tmp_path, [])
    with file.open('ab') as stream:
        stream.write(b'x' * (3 * 1024**2) + b'\n')
        stream.write((json.dumps(message(text='After the large record')) + '\n').encode())
        stream.write(json.dumps(message('user', text='Partial append')).encode()[:-2])
    monkeypatch.setattr(codex, 'MAX_SLICE_BYTES', 2 * 1024**2)
    monkeypatch.setattr(codex, 'MAX_SOURCES', 1)
    c = CodexCollector(config)
    assert checkpoint(c, engine) == []
    # A second source must get service before returning to the large session.
    archived = config.codex_data_dir / 'archived_sessions' / 'older.jsonl'
    archived.parent.mkdir()
    archived.write_bytes(file.read_bytes().split(b'\n')[0] + b'\n' +
                         json.dumps(message(text='Archived response')).encode() + b'\n')
    assert [m.content for m in checkpoint(c, engine)] == ['Archived response']
    seen = []
    for _ in range(8):
        seen.extend(checkpoint(c, engine))
    assert [m.content for m in seen] == ['After the large record']
    with file.open('ab') as stream:
        stream.write(json.dumps(message('user', text='Partial append')).encode()[-2:] + b'\n')
    seen = checkpoint(c, engine) + checkpoint(c, engine)
    assert [m.content for m in seen] == ['Partial append']


def test_v1_v2_dedup_scope_revision_and_opt_out(config, tmp_path, engine):
    session(config, tmp_path, [])
    cwd = config.codex_allowed_workspaces[0] / 'demo'
    summary(config, 'memories', cwd)
    v2 = summary(config, 'memories_v2', cwd)
    v2.write_text(v2.read_text('utf-8').replace('10:00:00Z', '11:00:00Z'), encoding='utf-8')
    summary(config, 'memories_v2', tmp_path / 'private', name='private')
    rows = checkpoint(CodexCollector(config), engine)
    assert len(rows) == 1 and rows[0].type == MemoryType.CODEX_CHAT
    assert rows[0].metadata['artifact'] == 'generated_memory'
    assert rows[0].metadata['status'] == 'candidato'
    assert CodexCollector(config).collect_all() == []
    v2.write_text(v2.read_text('utf-8').replace('Validated migration', 'Validated new migration'), encoding='utf-8')
    revision = checkpoint(CodexCollector(config), engine)
    assert len(revision) == 1 and revision[0].id != rows[0].id
    config.collect_codex_memories = False
    assert CodexCollector(config).collect_all() == []
    config.collect_codex_chat = False
    assert CodexCollector(config).collect_all() == []


def test_summary_secret_rejects_entire_document_and_no_global_import(config, tmp_path):
    session(config, tmp_path, [])
    summary(config, 'memories_v2', config.codex_allowed_workspaces[0],
            'Harmless paragraph\n\npassword=abcdefghijklmnopqrstuv')
    (config.codex_data_dir / 'memories_v2/memory_summary.md').write_text('Global personal knowledge', encoding='utf-8')
    c = CodexCollector(config)
    assert c.collect_all() == []
    assert c.diagnostics['sensitive_summaries_skipped'] == 1


def test_sqlite_wal_filters_and_cross_source_ids(config, tmp_path, engine):
    file = session(config, tmp_path, [message('user', text='Owned question'), message(text='Owned final')])
    json_rows = CodexCollector(config).collect_all()
    engine.index_batch(json_rows)
    db = history(config, config.codex_allowed_workspaces[0] / 'demo')
    try:
        add_item(db, 2, {'type': 'userMessage', 'content': [{'type': 'text', 'text': 'Owned question'}]})
        add_item(db, 3, {'type': 'agentMessage', 'phase': 'final_answer', 'text': 'Owned final'})
        add_item(db, 4, {'type': 'agentMessage', 'phase': 'commentary', 'text': 'Transient update'})
        add_item(db, 5, {'type': 'reasoning', 'text': 'Never collect'})
        add_item(db, 6, {'type': 'mcpToolCall', 'text': 'Never collect'})
        file.unlink()  # Codex migration removes the rollout but retains the projection.
        c = CodexCollector(config)
        sqlite_rows = c.collect_all()
        assert {m.id for m in sqlite_rows} == {m.id for m in json_rows}
        assert engine.index_batch(sqlite_rows) == 0
        c.acknowledge()
        assert CodexCollector(config).collect_all() == []
        add_item(db, 3, {'type': 'agentMessage', 'phase': 'final_answer', 'text': 'Updated final'}, updated=7)
        assert [m.content for m in checkpoint(CodexCollector(config), engine)] == ['Updated final']
        with pytest.raises(sqlite3.OperationalError), codex.readonly(
            config.codex_data_dir / 'thread_history_1.sqlite'
        ) as ro:
            ro.execute('DELETE FROM thread_items')
    finally:
        db.close()


def test_history_denies_unapproved_workspace_and_subagent(config, tmp_path):
    session(config, tmp_path, [])
    db = history(config, tmp_path / 'unapproved')
    add_item(db, 2, {'type': 'agentMessage', 'phase': 'final_answer', 'text': 'Private content'})
    db.close()
    assert CodexCollector(config).collect_all() == []
    state = sqlite3.connect(config.codex_data_dir / 'state_5.sqlite')
    state.execute('UPDATE threads SET cwd=?, source=?', (str(config.codex_allowed_workspaces[0]), '{"subagent":{}}'))
    state.commit()
    state.close()
    assert CodexCollector(config).collect_all() == []


def test_corrupt_checkpoint_and_unsupported_sqlite_preserve_json(config, tmp_path):
    session(config, tmp_path, [message()])
    c = CodexCollector(config)
    c.checkpoint_path.write_text('{partial', encoding='utf-8')
    sqlite3.connect(config.codex_data_dir / 'state_5.sqlite').close()
    sqlite3.connect(config.codex_data_dir / 'thread_history_1.sqlite').close()
    assert len(c.collect_all()) == 1
    assert c.diagnostics['history_unavailable'] == 1
