"""Bounded opt-in candidate exports; never auto-promote to verified/training."""
import logging
from .collector.models import MemoryType
from .obsidian import ObsidianManager, _sensitive_findings


def export_new_candidates(config, engine, memories):
    if not config.obsidian_auto_export_candidates:
        return 0
    safe = sorted((m for m in memories if m.type == MemoryType.CODEX_CHAT and not _sensitive_findings(m.content)), key=lambda m: m.timestamp)[-20:]
    if not safe:
        return 0
    manager = ObsidianManager(config, engine)
    exported = 0
    for vault in config.obsidian_vaults:
        if vault.enabled and vault.export_enabled:
            try:
                result = manager.export(vault.name, [m.id for m in safe], dry_run=False,
                                        actor='peer:codex', reason='Opt-in candidate feedback; verification remains required')
                exported += len(result.created) + len(result.updated)
                if result.created or result.updated:
                    manager.build_catalog(vault.name, actor='peer:codex')
            except (OSError, ValueError):
                logging.getLogger('animus.feedback').warning('Candidate export unavailable; next cycle retries without blocking sync')
    return exported
