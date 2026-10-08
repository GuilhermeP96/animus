---
name: animus
description: Reconcile substantive work with verified Obsidian knowledge and durable Animus memories, preserve validated decisions, and safely manage Animus memory, vault, peer, or hub operations when requested. Use for project analysis, implementation, debugging, architecture, operations, documentation, memory curation, or Animus administration.
---

# Animus

Use Obsidian as the governed knowledge layer and the Animus index as the broader source of memories, conversations, and evidence. Historical knowledge informs work; it does not override explicit user instructions, current repository state, tests, or verified runtime evidence.

## Operating modes

- **Consult** is the default for substantive project work: read verified knowledge and relevant memories before planning.
- **Preserve** records a validated, reusable outcome after work is complete.
- **Curate** exports or organizes selected knowledge in an Obsidian vault when requested or covered by an established policy.
- **Administer** installs, configures, synchronizes, updates, or operates an Animus peer/hub only when the task explicitly includes administration.

Do not infer permission for curation or administration merely because the tools are available.

## Required consultation workflow

1. Identify the current repository, project, goal, and likely sensitivity.
2. Call `animus_obsidian_guide` before any Obsidian operation. Treat the returned contract as authoritative if it is newer than this file.
3. Discover configured vaults with `animus obsidian status` when the vault is not known. Start from `.animus/exported/00 - Início.md` and the matching map under `.animus/exported/Sistema/Projetos/`.
4. Query `animus_obsidian_search` without candidates first. Cite the titles or IDs used. If no Gold result exists, say so.
5. Query `animus_recall` for durable prior context. Refine with `animus_search` when provenance, date, exact text, or broader evidence is required.
6. Use `animus_context` for a specific file/workspace, `animus_timeline` for recent continuity, and `animus_session_list` plus `animus_session` to resume a known conversation. Use `animus_related` to inspect context around an individual memory.
7. Reconcile knowledge and memory against current files, tests, configuration, and runtime state. Report contradictions, stale paths/versions, and uncertainty.

Authority within retrieved material is:

1. explicit current human instruction;
2. current repository instructions and verified live evidence;
3. explicit human-authored, verified Obsidian knowledge;
4. other verified Obsidian knowledge;
5. curated or candidate notes, clearly marked as hypotheses;
6. raw Animus history.

Newer material prevails only when it does not contradict an explicit human decision.

## Preserve durable memory

After validation, use `animus_remember` only for information that will change future work: decisions, architecture, procedures, constraints, non-obvious fixes, verified commands, migration results, or explicit preferences.

- Include repository/workspace, affected component, outcome, provenance, and validation performed.
- Use focused tags such as `decision`, `architecture`, `fix`, `test`, `release`, or `operations`.
- Do not store verbose transcripts, obvious source facts, transient logs, failed attempts without a reusable lesson, or duplicates.
- Never store passwords, tokens, private keys, connection strings, `.env` contents, personal data, raw customer data, or sensitive production payloads.

## Governed Obsidian consultation

- `animus_obsidian_search` returns `status: verificado` by default. This is the Gold layer suitable for RAG and decisions.
- Set `include_candidates: true` only to investigate leads. Identify every `candidato` or `curado` result as **UNVERIFIED** and confirm it against sources or raw memory.
- Prefer updating an existing subject note over creating a duplicate. Every promoted note needs one primary subject, descriptive title, project, type, status, sensitivity, source, project-map link, and useful related links.
- Preserve `projeto_manual: true`; it records a deliberate human classification.
- Use factual and changing knowledge for RAG. Do not convert ordinary notes into fine-tuning instruction/response pairs by assumption.

Read [docs/CAMADA-CONHECIMENTO-OBSIDIAN.md](docs/CAMADA-CONHECIMENTO-OBSIDIAN.md) when the task involves lifecycle, metadata, RAG/SFT eligibility, curation health, or knowledge maintenance. Read [docs/PLANO-INTEGRACAO-OBSIDIAN.md](docs/PLANO-INTEGRACAO-OBSIDIAN.md) for architecture, synchronization, conflict, and rollback design.

## Governed Obsidian management

Full technical access does not remove the vault's governance boundary.

1. Select reusable source memories and check for an existing note.
2. Run `animus_obsidian_export` as a dry-run first. Automatic exports remain `candidato`; export success is not verification.
3. Run `animus_obsidian_organize` in `propose`/dry-run mode first. Review project, path, links, duplicates, sensitivity, and diff.
4. Apply only within `.animus/exported/` when the current request or an established policy authorizes it.
5. Never overwrite, move, or rename human notes outside `.animus/exported/` without explicit approval.
6. Send hash conflicts to `.animus/quarantine/`; never force an overwrite.
7. After an applied change, regenerate the catalog, inspect orphans/duplicates, record the reason in the audit trail, and verify that rollback remains available. Use the CLI for catalog or rollback when MCP does not expose the operation.

The lifecycle is `candidato → curado → verificado → aprovado_para_treino`. Do not skip stages:

- `curado` means structure, project, duplicates, and links were reviewed.
- `verificado` means the content was checked against its source and has no known contradiction.
- Fine-tuning additionally requires a complete instruction/response pair, `treino.aprovado: true`, and `sensibilidade: publico`; internal material requires explicit inclusion.
- Run `animus_obsidian_dataset` in dry-run mode before building either RAG or SFT datasets.

## Collection, synchronization, and administration

- Do not run `animus_collect` routinely; it may scan large local histories. Use it only when requested or when missing indexing is demonstrated and collection is in scope.
- `animus obsidian collect` indexes configured human vault content. Managed files under `.animus/exported/` can remain directly searchable even when the human-note indexed count is zero.
- Use `animus_stats` to inspect memory/sync health and `animus sync` only when synchronization is part of the task or stale peer state is established.
- Do not install, reconfigure, restart, self-update, or change peer identity/hub secrets during ordinary consultation.
- For peer/hub administration, read [CLAUDE.md](CLAUDE.md), [README.md](README.md), current configuration, and the relevant installer/deploy script before acting. Never expose `ANIMUS_SERVER_SECRET`.

## Failure handling

If verified Obsidian knowledge is absent, continue with current evidence and Animus memory while stating that no Gold note supported the decision. If Animus is unavailable, report that reconciliation could not be completed and continue only when local evidence is sufficient and safe. Never pretend a memory, sync, collection, export, or validation succeeded.
