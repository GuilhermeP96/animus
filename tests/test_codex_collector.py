import json
from pathlib import Path

from animus.collector.codex import CodexCollector
from animus.collector.models import MemoryType


def session(config, tmp_path, records):
    config.codex_data_dir = tmp_path / 'codex'
    root = tmp_path / 'projects'
    root.mkdir(exist_ok=True)
    config.codex_allowed_workspaces = [root]
    config.collect_codex_chat = True
    file = config.codex_data_dir / 'sessions/run.jsonl'
    file.parent.mkdir(parents=True, exist_ok=True)
    meta = {'type':'session_meta','payload':{'id':'owned-fixture','cwd':str(root/'demo')}}
    file.write_text('\n'.join(json.dumps(x) for x in [meta, *records])+'\n', encoding='utf-8')
    return file


def message(role='assistant', phase='final_answer', text='Validated source and retained backup'):
    return {'timestamp':'2026-10-20T10:00:00Z','type':'response_item',
            'payload':{'type':'message','role':role,'phase':phase,
                       'content':[{'type':'output_text','text':text}]}}


def test_default_disabled_and_workspace_consent_required(config,tmp_path):
    session(config,tmp_path,[message()])
    config.collect_codex_chat=False
    assert CodexCollector(config).collect_all()==[]
    config.collect_codex_chat=True;config.codex_allowed_workspaces=[]
    assert CodexCollector(config).collect_all()==[]


def test_only_scoped_user_final_messages_and_stable_dedup(config,tmp_path,engine):
    records=[message('user',text='Repair the updater'),message(),message(phase='commentary'),
             message(phase='analysis'),message(role='developer'),
             {'type':'response_item','payload':{'type':'function_call_output','output':'secret tool output'}},
             {'type':'turn_context','payload':{'cwd':str(tmp_path/'unapproved')}},message()]
    session(config,tmp_path,records)
    rows=CodexCollector(config).collect_all()
    assert len(rows)==2 and all(r.type==MemoryType.CODEX_CHAT for r in rows)
    assert rows[0].metadata['status']=='candidato'
    assert engine.index_batch(rows)==2
    assert engine.index_batch(CodexCollector(config).collect_all())==0


def test_secrets_context_and_citation_handling(config,tmp_path):
    session(config,tmp_path,[message(text='password=abcdefghijklmnopqrstuv'),
          message('user',text='<environment_context>private context</environment_context>'),
          message(text='Source verified\n<oai-mem-citation>internal annotation</oai-mem-citation>')])
    collector=CodexCollector(config);rows=collector.collect_all()
    assert len(rows)==1 and rows[0].content=='Source verified'
    assert collector.diagnostics['sensitive_messages_skipped']==1


def test_partial_append_and_oversized_record_do_not_hide_next_message(config,tmp_path):
    file=session(config,tmp_path,[])
    with file.open('ab') as f:
        f.write(b'x'*(1024**2+1)+b'\n')
        f.write((json.dumps(message())+'\n').encode())
        f.write(b'{"incomplete":')
    assert len(CodexCollector(config).collect_all())==1
