"""Canonical-vault desktop journeys, using only owned synthetic profiles."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animus.collector.obsidian import ObsidianCollector, note_id, parse_frontmatter
from animus.config import ObsidianVaultConfig
from animus.desktop_knowledge import KnowledgeConflict, KnowledgeService, _edit_lock


@pytest.fixture
def knowledge(config, engine, tmp_path):
    vault = tmp_path / "vault with spaces"
    vault.mkdir()
    config.collect_obsidian = True
    config.obsidian_vaults = [ObsidianVaultConfig(name="canonical", path=vault)]
    return KnowledgeService(config, engine), vault


def write(vault, name="Note.md", body="Synthetic knowledge", metadata="status: candidato\n"):
    p = vault / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\n" + metadata + "---\n" + body, encoding="utf-8")
    return p


def test_list_search_status_and_internal_namespaces(knowledge):
    service, vault = knowledge
    write(
        vault,
        metadata="title: Shared decision\nprojeto: Animus\nstatus: verificado\n",
        body="Ação, João e ç",
    )
    write(vault, "Other.md", body="Other candidate")
    write(vault, ".animus/exported/Conhecimento/Curated.md", body="Curated candidate")
    for name in [".animus/backups/Hidden.md", ".obsidian/Hidden.md", "nested/.git/Hidden.md"]:
        write(vault, name, body="Must stay hidden")
    rows = service.list_notes("canonical")
    assert rows["total"] == 3
    found = service.list_notes("canonical", "João", "verificado")["notes"]
    assert len(found) == 1 and found[0]["projeto"] == "Animus"
    assert service.list_notes("canonical", "absent")["total"] == 0


def test_create_in_same_vault_and_same_index_queue(knowledge):
    s, vault = knowledge
    config_hash = s.config.model_dump_json()
    result = s.create("canonical", "Ação João", "# Ação\n\nDecisão confirmada.", "Animus")
    note = result["note"]
    path = vault / note["path"]
    assert result["saved"] and result["indexed"] and path.is_file()
    assert note["status"] == "candidato" and note["sync_state"] == "pending"
    row = s.engine.get_memory(note_id("canonical", note["path"]))
    assert row["source_path"] == "obsidian://canonical/" + note["path"] and row["synced"] == 0
    assert json.loads((s.config.data_dir / "peer-command.json").read_text()) == {"action": "sync"}
    assert s.config.model_dump_json() == config_hash
    with pytest.raises(KnowledgeConflict):
        s.create("canonical", "Ação João", "Other content")
    assert s.engine.conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 1


def test_save_preserves_bom_crlf_unknown_yaml_and_audits_without_duplicate(knowledge):
    s, vault = knowledge
    raw = b"\xef\xbb\xbf---\r\n# Keep this comment\r\nstatus: candidato\r\ncustom:\r\n  nested: [a, b]\r\n---\r\nOriginal body\r\n"
    p = vault / "Note.md"
    p.write_bytes(raw)
    note = s.read("canonical", "Note.md")
    result = s.save("canonical", "Note.md", note["etag"], "Ação, João e ç\n", {"projeto": "Animus"})
    saved = p.read_bytes()
    assert (
        saved.startswith(b"\xef\xbb\xbf")
        and b"\r\n" in saved
        and b"\n" not in saved.replace(b"\r\n", b"")
    )
    assert b"# Keep this comment\r\n" in saved and b"custom:\r\n  nested: [a, b]\r\n" in saved
    assert next((vault / ".animus/backups").rglob("*.bak")).read_bytes() == raw
    meta, _, _ = parse_frontmatter(saved.decode("utf-8-sig"))
    assert meta["projeto_manual"] is True and meta["custom"] == {"nested": ["a", "b"]}
    assert result["note"]["sync_state"] == "pending"
    rows = ObsidianCollector(s.config).collect_all()
    assert len(rows) == 1 and rows[0].id == note_id("canonical", "Note.md")
    s.engine.index_batch(rows)
    assert s.read("canonical", "Note.md")["sync_state"] == "pending"
    audit = json.loads((vault / ".animus/audit.jsonl").read_text().splitlines()[-1])
    assert (
        audit["action"] == "updated"
        and audit["backup"]
        and "Original body" not in json.dumps(audit)
    )


def test_concurrent_file_edit_fails_without_overwrite(knowledge):
    s, vault = knowledge
    p = write(vault)
    note = s.read("canonical", "Note.md")
    p.write_text("External editor revision", encoding="utf-8")
    with pytest.raises(KnowledgeConflict):
        s.save("canonical", "Note.md", note["etag"], "GUI draft")
    assert p.read_text() == "External editor revision"
    assert not (vault / ".animus/backups").exists()


def test_second_gui_writer_is_locked(knowledge):
    s, vault = knowledge
    write(vault)
    note = s.read("canonical", "Note.md")
    with _edit_lock(s.config.data_dir, "canonical/Note.md"), pytest.raises(OSError):
        s.save("canonical", "Note.md", note["etag"], "Second writer")


def test_verified_status_requires_explicit_review_again_after_body_edit(knowledge):
    s, vault = knowledge
    write(vault)
    note = s.read("canonical", "Note.md")
    with pytest.raises(PermissionError):
        s.save("canonical", "Note.md", note["etag"], note["body"], {"status": "verificado"})
    result = s.save(
        "canonical",
        "Note.md",
        note["etag"],
        note["body"],
        {"status": "verificado"},
        verified_ack=True,
    )
    verified = result["note"]
    assert verified["status"] == "verificado"
    with pytest.raises(PermissionError):
        s.save("canonical", "Note.md", verified["etag"], "Changed facts")
    result = s.save("canonical", "Note.md", verified["etag"], "Changed facts", {"status": "curado"})
    assert result["note"]["status"] == "curado"


@pytest.mark.parametrize(
    "relative",
    [
        "../outside.md",
        "/outside.md",
        "C:/outside.md",
        ".obsidian/secret.md",
        ".animus/backups/secret.md",
        "nested/.git/secret.md",
        "note.txt",
    ],
)
def test_scope_blocks_traversal_internal_files_and_wrong_extensions(knowledge, relative):
    s, _ = knowledge
    with pytest.raises(PermissionError):
        s.save("canonical", relative, "", "Not allowed", create=True)


def test_secrets_invalid_status_and_unsupported_metadata_never_write(knowledge):
    s, vault = knowledge
    p = write(vault)
    before = p.read_bytes()
    note = s.read("canonical", "Note.md")
    with pytest.raises(PermissionError):
        s.save("canonical", "Note.md", note["etag"], "password=abcdefghijklmnopqrstuv")
    for patch_value in [
        {"status": "automatic_verified"},
        {"title": "Injected\nmetadata"},
        {"animus": {}},
    ]:
        with pytest.raises(ValueError):
            s.save("canonical", "Note.md", note["etag"], "Safe body", patch_value)
    assert p.read_bytes() == before


def test_disabled_collection_keeps_canonical_source_readonly(knowledge):
    s, vault = knowledge
    write(vault)
    s.config.collect_obsidian = False
    note = s.read("canonical", "Note.md")
    assert not note["editable"]
    with pytest.raises(PermissionError):
        s.save("canonical", "Note.md", note["etag"], "Changed")


def test_approved_training_and_invalid_yaml_are_not_silently_rewritten(knowledge):
    s, vault = knowledge
    write(vault, metadata="status: verificado\ntreino:\n  aprovado: true\n")
    note = s.read("canonical", "Note.md")
    assert not note["editable"] and "treino" in note["warning"]
    with pytest.raises(PermissionError):
        s.save("canonical", "Note.md", note["etag"], "Changed", verified_ack=True)
    p = vault / "Invalid.md"
    p.write_text("---\nstatus: [broken\n---\nReadable", encoding="utf-8")
    note = s.read("canonical", "Invalid.md")
    assert not note["editable"]
    with pytest.raises(ValueError):
        s.save("canonical", "Invalid.md", note["etag"], "Changed")


def test_canonical_file_survives_index_failure_and_recovers_next_collection(knowledge, monkeypatch):
    s, vault = knowledge
    write(vault)
    note = s.read("canonical", "Note.md")
    with monkeypatch.context() as m:

        def fail(*a, **k):
            raise sqlite3.OperationalError("synthetic lock")

        m.setattr(s.engine, "index_memory", fail)
        result = s.save("canonical", "Note.md", note["etag"], "Durable edit")
    assert (
        result["saved"]
        and not result["indexed"]
        and "Durable edit" in (vault / "Note.md").read_text()
    )
    s.engine.index_batch(ObsidianCollector(s.config).collect_all())
    assert s.read("canonical", "Note.md")["sync_state"] == "pending"


def test_managed_curated_notes_keep_sync_identity_and_do_not_become_missing(knowledge):
    s, vault = knowledge
    relative = ".animus/exported/Conhecimento/Project/Note.md"
    write(vault, relative)
    note = s.read("canonical", relative)
    s.save("canonical", relative, note["etag"], "Explicit human curation", {"status": "curado"})
    result = s.refresh("canonical")
    assert result["indexed"] == 1
    row = s.engine.get_memory(note_id("canonical", relative))
    assert json.loads(row["metadata"])["missing"] is False
    s.config.obsidian_exclude_patterns.append(".animus/exported/Conhecimento/Project/**")
    assert ObsidianCollector(s.config).collect_all() == []


def test_pagination_and_visible_scan_budget(knowledge, monkeypatch):
    s, vault = knowledge
    for i in range(53):
        write(vault, f"Note{i:03}.md")
    first = s.list_notes("canonical")
    last = s.list_notes("canonical", offset=50)
    assert len(first["notes"]) == 50 and first["has_more"] and len(last["notes"]) == 3
    assert not last["has_more"] and last["total"] == 53
    monkeypatch.setattr("animus.desktop_knowledge.MAX_FILES", 1)
    assert s.list_notes("canonical")["truncated"]


def test_sync_uses_existing_authenticated_channel_and_marks_note_received(knowledge):
    s, _ = knowledge
    note = s.create("canonical", "Sync test", "Safe canonical body")["note"]
    s.config.hub_url = "https://hub.invalid"
    response = MagicMock(status_code=200)
    response.json.return_value = {"ok": True}
    with patch("animus.network.peer.httpx.AsyncClient") as client:
        client.return_value.__aenter__.return_value.post = AsyncMock(return_value=response)
        result = s.synchronize()
    assert result["sent"] == 1 and result["pending_notes"] == 0
    assert s.read("canonical", note["path"])["sync_state"] == "synced"


def test_stdio_json_roundtrip_uses_configured_profile_and_redacts_errors(knowledge, tmp_path):
    s, _ = knowledge
    s.config.save()
    source = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "ANIMUS_DATA_DIR": str(s.config.data_dir),
        "PYTHONPATH": str(source),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    request = {
        "op": "create",
        "vault": "canonical",
        "title": "João e ação",
        "body": "# ação\n\nJoão e ç",
    }

    def run(value):
        p = subprocess.run(
            [sys.executable, "-m", "animus.desktop_knowledge"],
            input=json.dumps(value, ensure_ascii=False),
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
        assert p.returncode == 0
        return json.loads(p.stdout), p.stdout

    result, _ = run(request)
    assert result["ok"] and result["data"]["note"]["body"] == request["body"]
    request["title"] = "Secret"
    request["body"] = "password=abcdefghijklmnopqrstuv"
    result, raw = run(request)
    assert (
        not result["ok"]
        and "abcdefghijklmnopqrstuv" not in raw
        and str(s.config.data_dir) not in raw
    )


def test_note_symlink_never_targets_another_directory(knowledge, tmp_path):
    s, vault = knowledge
    outside = tmp_path / "outside.md"
    outside.write_text("Retain outside")
    link = vault / "Link.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("host cannot create symlinks")
    with pytest.raises(PermissionError):
        s.read("canonical", "Link.md")
    assert outside.read_text() == "Retain outside"


def test_full_markdown_and_mermaid_survive_index_and_wire_roundtrip(knowledge, tmp_path):
    from animus.collector.models import MemoryBatch
    from animus.indexer.engine import IndexEngine
    from animus.network.sync import SyncProtocol

    s, vault = knowledge
    markdown = (
        "# Diagrama\n\n| A | B |\n|---|---|\n| x | y |\n\n```mermaid\nflowchart LR\nA --> B\n```\n"
    )
    result = s.create("canonical", "Lossless Markdown", markdown)
    relative = result["note"]["path"]
    memory = ObsidianCollector(s.config).collect_all()[0]
    row = s.engine.get_memory(memory.id)
    assert row["content"] == (vault / relative).read_text("utf-8")
    batch = MemoryBatch(node_id=s.config.node_id, node_name="Fixture", memories=[memory])
    received, _ = SyncProtocol.memories_from_push(json.loads(SyncProtocol.push(batch)))
    remote = IndexEngine(tmp_path / "remote.db")
    try:
        remote.index_batch(received, synced=True)
        assert remote.get_memory(memory.id)["content"] == row["content"]
        assert "```mermaid\n" in row["content"] and "|---|---|" in row["content"]
    finally:
        remote.close()


def test_wikilinks_are_resolved_in_canonical_scope_and_ambiguity_is_explicit(knowledge):
    s, vault = knowledge
    write(vault, "Folder/Current.md")
    write(vault, "Target.md", body="Target canonical")
    assert s.resolve("canonical", "Folder/Current.md", "../Target")["path"] == "Target.md"
    write(vault, "one/Same.md")
    write(vault, "two/Same.md")
    with pytest.raises(ValueError):
        s.resolve("canonical", "Folder/Current.md", "Same")
    for reference in ["https://example.invalid/Note.md", "../../outside.md", ".obsidian/secret"]:
        with pytest.raises((ValueError, PermissionError)):
            s.resolve("canonical", "Current.md", reference)


def test_images_are_local_bounded_and_not_an_arbitrary_file_reader(knowledge, monkeypatch):
    import base64

    s, vault = knowledge
    image = vault / "attachments/logo.png"
    image.parent.mkdir()
    raw = (Path(__file__).resolve().parents[1] / "desktop/windows/assets/datano.png").read_bytes()
    image.write_bytes(raw)
    result = s.attachment("canonical", "Note.md", "logo.png")
    assert base64.b64decode(result["data_url"].split(",", 1)[1]) == raw
    secret = vault / "attachments/not-image.png"
    secret.write_text("Not image data", encoding="utf-8")
    for reference in [
        "not-image.png",
        "https://example.invalid/img.png",
        "../../img.png",
        "Note.md",
    ]:
        with pytest.raises((ValueError, PermissionError)):
            s.attachment("canonical", "Note.md", reference)
    monkeypatch.setattr("animus.desktop_knowledge.MAX_IMAGE_BYTES", 1)
    with pytest.raises(ValueError):
        s.attachment("canonical", "Note.md", "logo.png")


def test_svg_attachments_reject_document_types_and_entities(knowledge):
    s, vault = knowledge
    svg = vault / "image.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><text>Safe</text></svg>', encoding="utf-8"
    )
    assert s.attachment("canonical", "Note.md", "image.svg")["data_url"].startswith(
        "data:image/svg+xml;"
    )
    svg.write_text('<!DOCTYPE svg [<!ENTITY x "expanded">]><svg>&x;</svg>', encoding="utf-8")
    with pytest.raises(ValueError):
        s.attachment("canonical", "Note.md", "image.svg")


def test_internal_case_variants_are_not_note_or_image_sources(knowledge):
    s, vault = knowledge
    write(vault, ".ANIMUS/backups/Private.md")
    internal = vault / ".ANIMUS/backups/private.svg"
    internal.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    with pytest.raises(PermissionError):
        s.read("canonical", ".ANIMUS/backups/Private.md")
    for reference in [".ANIMUS/backups/private.svg", "private.svg"]:
        with pytest.raises((ValueError, PermissionError)):
            s.attachment("canonical", "Note.md", reference)
    nested = ".animus/exported/Conhecimento/.animus/backups/Hidden.md"
    write(vault, nested)
    with pytest.raises(PermissionError):
        s.read("canonical", nested)


@pytest.mark.skipif(os.name != "nt", reason="Windows exclusive writer sharing")
def test_windows_commit_denies_concurrent_write_and_replacement(knowledge, monkeypatch):
    s, vault = knowledge
    path = write(vault)
    note = s.read("canonical", path.name)
    original_backup = s.manager._backup
    attempts = []

    def backup(root, relative, target):
        # First backup is optimistic; the second is inside the held source handle.
        attempts.append(True)
        if len(attempts) == 2:
            with pytest.raises(PermissionError):
                target.write_text("Concurrent overwrite", encoding="utf-8")
            other = vault / "replacement.tmp"
            other.write_text("Concurrent replacement", encoding="utf-8")
            with pytest.raises(PermissionError):
                os.replace(other, target)
        return original_backup(root, relative, target)

    monkeypatch.setattr(s.manager, "_backup", backup)
    result = s.save("canonical", path.name, note["etag"], "Saved under exclusive handle")
    assert result["saved"] and len(attempts) == 2
