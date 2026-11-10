from unittest.mock import AsyncMock, patch

import pytest
from animus.collector.models import Memory, MemoryType
from animus.mcp import AnimusMCPServer


@pytest.fixture
def server(config, engine):
    value=AnimusMCPServer.__new__(AnimusMCPServer)
    value.config=config;value.engine=engine;config.hub_url='https://hub.example.invalid'
    return value


def test_remote_rag_is_opt_in_and_can_be_disabled_per_call(server):
    with patch('animus.network.peer.AnimusPeer.remote_search',new_callable=AsyncMock) as call:
        assert server._hydrate_hub('topic',{})=='not_requested'
        server.config.rag_hub_enabled=True
        assert server._hydrate_hub('topic',{'remote':False})=='not_requested'
        call.assert_not_called()


def test_remote_search_caches_only_relevant_results_without_echo(server):
    memory=Memory(type=MemoryType.SESSION_NOTE,source_node='remote-peer',workspace='animus',
                  title='Remote architecture',content='unique_remote_architecture decision from a different machine')
    with patch('animus.network.peer.AnimusPeer.remote_search',new_callable=AsyncMock,return_value=[memory.model_dump(mode='json')]) as call:
        output=server._tool_search({'query':'unique_remote_architecture','workspace':'animus','remote':True,'limit':2})
    assert 'Remote architecture' in output and 'Hub retrieval: queried' in output
    assert server.engine.get_memory(memory.id)['synced']==1
    assert call.call_args.kwargs=={'workspace':'animus','mem_type':'','limit':20,'strict':True}


def test_scoped_hub_miss_retries_once_without_workspace(server):
    memory=Memory(type=MemoryType.CODEX_CHAT,source_node='remote-peer',workspace='repo',
                  title='Parent workspace decision',content='preserve the consolidated encoding decision')
    with patch('animus.network.peer.AnimusPeer.remote_search',new_callable=AsyncMock,
               side_effect=[[],[memory.model_dump(mode='json')]]) as call:
        output=server._tool_recall({'context':'consolidated encoding decision',
                                    'workspace':'datano-agents','remote':True})
    assert 'Parent workspace decision' in output
    assert 'scoped miss, global fallback' in output
    assert call.call_count==2
    assert call.call_args_list[0].kwargs['workspace']=='datano-agents'
    assert call.call_args_list[1].kwargs['workspace']==''


def test_hub_failure_is_explicit_not_a_false_no_history(server):
    with patch('animus.network.peer.AnimusPeer.remote_search',new_callable=AsyncMock,side_effect=RuntimeError('unavailable')):
        output=server._tool_recall({'context':'recovery','remote':True})
    assert 'unavailable' in output and 'local only' in output
