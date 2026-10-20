from animus.collector.models import Memory, MemoryType
from animus.config import ObsidianVaultConfig
from animus.knowledge_feedback import export_new_candidates


def test_feedback_is_opt_in_bounded_and_candidates_only(config,engine,tmp_path):
    vault=tmp_path/'vault';vault.mkdir()
    config.obsidian_vaults=[ObsidianVaultConfig(name='qa',path=vault,export_enabled=True)]
    memory=Memory(type=MemoryType.CODEX_CHAT,source_node=config.node_id,workspace='animus',
                  content='Check the authenticated update receipt before declaring recovery',title='Animus recovery')
    engine.index_batch([memory])
    assert export_new_candidates(config,engine,[memory])==0
    config.obsidian_auto_export_candidates=True
    assert export_new_candidates(config,engine,[memory])==1
    exports=list((vault/'.animus/exported').rglob('*--'+memory.id[:8]+'.md'))
    assert len(exports)==1
    text=exports[0].read_text(encoding='utf-8')
    assert 'candidato' in text and 'verificado' not in text
    assert export_new_candidates(config,engine,[memory])==0
