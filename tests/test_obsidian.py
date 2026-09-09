"""Acceptance tests for the Obsidian knowledge layer."""

import json

import pytest

from animus.collector.models import Memory, MemoryType
from animus.collector.obsidian import ObsidianCollector, extract_links, parse_frontmatter
from animus.config import ObsidianVaultConfig
from animus.obsidian import ObsidianManager, sanitize_title


@pytest.fixture
def obsidian_config(config, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    config.collect_obsidian = True
    config.obsidian_vaults = [
        ObsidianVaultConfig(
            name="knowledge",
            path=vault,
            export_enabled=True,
        )
    ]
    return config, vault


def test_frontmatter_tags_and_links_are_parsed(obsidian_config):
    config, vault = obsidian_config
    (vault / "Projeto.md").write_text(
        "---\ntitle: Projeto Animus\ntags: [projeto, memoria]\nworkspace: animus\n---\n"
        "Conecta [[Animus#MCP|Animus]] a [outra nota](Notas/Outra.md) #curado\n",
        encoding="utf-8",
    )

    memories = ObsidianCollector(config).collect_all()

    assert len(memories) == 1
    memory = memories[0]
    assert memory.type == MemoryType.OBSIDIAN_NOTE
    assert memory.title == "Projeto Animus"
    assert memory.workspace == "animus"
    assert set(memory.tags) == {"projeto", "memoria", "curado"}
    assert memory.metadata["obsidian_links"] == ["Animus", "Notas/Outra.md"]
    assert memory.source_path == "obsidian://knowledge/Projeto.md"
    assert str(vault) not in memory.source_path


def test_invalid_frontmatter_does_not_abort_vault(obsidian_config):
    config, vault = obsidian_config
    (vault / "Ruim.md").write_text("---\ntags: [broken\n---\nAinda pesquisavel", encoding="utf-8")
    (vault / "Boa.md").write_text("Conteudo valido", encoding="utf-8")
    collector = ObsidianCollector(config)

    assert len(collector.collect_all()) == 2
    assert len(collector.diagnostics) == 1
    assert collector.diagnostics[0]["relative_path"] == "Ruim.md"


def test_exclusions_and_collection_opt_in(obsidian_config):
    config, vault = obsidian_config
    (vault / "Nota.md").write_text("visivel", encoding="utf-8")
    for folder in (".obsidian", ".animus/exported", "attachments", "node_modules"):
        target = vault / folder
        target.mkdir(parents=True)
        (target / "Ignorar.md").write_text("ignorar", encoding="utf-8")
    assert [m.title for m in ObsidianCollector(config).collect_all()] == ["Nota"]
    config.collect_obsidian = False
    assert ObsidianCollector(config).collect_all() == []


def test_note_edit_updates_stable_memory_and_removal_is_marked(obsidian_config, engine):
    config, vault = obsidian_config
    note = vault / "Decisao.md"
    note.write_text("Primeira decisao", encoding="utf-8")
    collector = ObsidianCollector(config)
    first = collector.collect_all()
    assert engine.index_batch(first) == 1
    memory_id = first[0].id
    assert engine.index_batch(collector.collect_all()) == 0

    note.write_text("Segunda decisao definitiva", encoding="utf-8")
    second = collector.collect_all()
    assert second[0].id == memory_id
    assert engine.index_batch(second) == 1
    assert engine.get_stats()["total_memories"] == 1
    assert engine.search("definitiva")[0]["id"] == memory_id

    note.unlink()
    collector.collect_all()
    assert engine.mark_obsidian_missing("knowledge", config.node_id, set()) == 1
    assert engine.search("definitiva") == []
    metadata = json.loads(engine.get_memory(memory_id)["metadata"])
    assert metadata["missing"] is True


def test_synced_note_update_propagates_but_cannot_replace_local_authority(obsidian_config, engine):
    config, vault = obsidian_config
    note = vault / "Compartilhada.md"
    note.write_text("Versao local", encoding="utf-8")
    local = ObsidianCollector(config).collect_all()[0]
    engine.index_memory(local)

    remote_other_node = local.model_copy(deep=True)
    remote_other_node.source_node = "other-node"
    remote_other_node.content = "Tentativa remota"
    remote_other_node.metadata["content_hash"] = "remote"
    assert engine.index_memory(remote_other_node, synced=True) is False
    assert "Versao local" in engine.get_memory(local.id)["content"]

    hub_engine_path = config.data_dir / "hub.db"
    from animus.indexer.engine import IndexEngine

    hub = IndexEngine(hub_engine_path)
    try:
        assert hub.index_memory(local, synced=True) is True
        edited = local.model_copy(deep=True)
        edited.content = "Versao propagada"
        edited.metadata["content_hash"] = "changed"
        assert hub.index_memory(edited, synced=True) is True
        assert "Versao propagada" in hub.get_memory(local.id)["content"]
    finally:
        hub.close()


def test_export_is_idempotent_and_manual_collision_is_quarantined(obsidian_config, engine):
    config, vault = obsidian_config
    memory = Memory(
        type=MemoryType.SESSION_NOTE,
        source_node=config.node_id,
        title='Plano: "MVP"',
        content="Uma memoria curada.",
        tags=["obsidian"],
    )
    engine.index_memory(memory)
    manager = ObsidianManager(config, engine)

    first = manager.export("knowledge", [memory.id])
    assert len(first.created) == 1
    exported = vault / first.created[0]
    text = exported.read_text(encoding="utf-8")
    metadata, body, warning = parse_frontmatter(text)
    assert warning is None
    assert metadata["animus"]["memory_id"] == memory.id
    assert metadata["animus"]["managed"] is True
    assert "Uma memoria curada." in body

    second = manager.export("knowledge", [memory.id])
    assert second.unchanged == first.created

    other = Memory(
        type=MemoryType.SESSION_NOTE,
        source_node=config.node_id,
        title="Manual",
        content="Nao sobrescrever",
    )
    engine.index_memory(other)
    manual_target = vault / ".animus" / "exported" / f"Manual--{other.id[:8]}.md"
    manual_target.write_text("Nota humana", encoding="utf-8")
    conflict = manager.export("knowledge", [other.id])
    assert manual_target.read_text(encoding="utf-8") == "Nota humana"
    assert len(conflict.conflicts) == 1
    assert (vault / conflict.conflicts[0]).is_file()


def test_edited_managed_note_conflicts_and_organization_requires_approval(obsidian_config, engine):
    config, vault = obsidian_config
    memory = Memory(
        type=MemoryType.SESSION_NOTE,
        source_node=config.node_id,
        title="Sintese",
        content="Corpo original",
    )
    engine.index_memory(memory)
    manager = ObsidianManager(config, engine)
    created = manager.export("knowledge", [memory.id])
    target = vault / created.created[0]
    target.write_text(target.read_text(encoding="utf-8") + "Edicao humana\n", encoding="utf-8")
    assert manager.export("knowledge", [memory.id]).conflicts

    proposal = manager.propose_organization("knowledge", [memory.id], actor="test-agent")
    assert proposal["mode"] == "propose"
    assert proposal["managed_scope"] is True
    with pytest.raises(PermissionError):
        manager.apply_organization(proposal, approved=False)


def test_helpers_cover_plain_notes_and_safe_names():
    metadata, body, warning = parse_frontmatter("# Sem YAML\nTexto")
    assert (metadata, body, warning) == ({}, "# Sem YAML\nTexto", None)
    assert extract_links("[[A|alias]] [B](Pasta/B.md) [site](https://example.com)") == [
        "A",
        "Pasta/B.md",
    ]
    assert sanitize_title('A<B>:C/"D"') == "A-B--C--D"


def test_config_roundtrip_and_created_note_rollback(obsidian_config, engine):
    config, vault = obsidian_config
    config.save()
    from animus.config import AnimusConfig

    loaded = AnimusConfig.load(config.config_path)
    assert loaded.obsidian_vaults[0].name == "knowledge"
    assert loaded.obsidian_vaults[0].path == vault
    assert loaded.collect_obsidian is True

    memory = Memory(
        type=MemoryType.SESSION_NOTE,
        source_node=config.node_id,
        title="Reversivel",
        content="Pode ser revertida",
    )
    engine.index_memory(memory)
    manager = ObsidianManager(config, engine)
    result = manager.export("knowledge", [memory.id])
    target = vault / result.created[0]
    assert target.is_file()
    assert manager.rollback_last("knowledge") == result.created[0]
    assert not target.exists()
    assert list((vault / ".animus" / "backups").rglob(target.name))


def test_vault_layout_metadata_is_non_destructive(obsidian_config):
    config, vault = obsidian_config
    from animus.obsidian import initialize_vault

    marker = vault / ".animus" / "README.md"
    initialize_vault(config.obsidian_vaults[0])
    assert (vault / ".animus" / "exported").is_dir()
    assert (
        json.loads((vault / ".animus" / "config.json").read_text(encoding="utf-8"))["vault"]
        == "knowledge"
    )
    marker.write_text("custom", encoding="utf-8")
    initialize_vault(config.obsidian_vaults[0])
    assert marker.read_text(encoding="utf-8") == "custom"


def test_mcp_definitions_expose_obsidian_operations():
    from animus.mcp import AnimusMCPServer

    names = {tool["name"] for tool in AnimusMCPServer.TOOL_DEFINITIONS}
    assert "animus_obsidian_export" in names
    assert "animus_obsidian_organize" in names
