"""Safe export and agent-organization layer for Obsidian vaults."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from .collector.obsidian import note_id, parse_frontmatter
from .config import AnimusConfig, ObsidianVaultConfig
from .indexer.engine import IndexEngine


AGENT_GUIDE = """# Guia dos Agentes — Camada Obsidian

> [!important] Contrato operacional
> O Obsidian é a camada de conhecimento durável e navegável. O índice Animus/MCP
> continua sendo a fonte para conversas brutas, evidências e recuperação ampla.

## Antes de responder ou executar

1. Identifique o projeto e abra o respectivo mapa em `Sistema/Projetos/`.
2. Leia primeiro notas `status: verificado`; trate `candidato` e `curado` como hipótese.
3. Use `animus_obsidian_search` para consultar a camada verificada. Consulte
   `animus_search` quando precisar confirmar origem, data ou contexto bruto.
4. Compare datas e fontes. Nota humana explícita prevalece sobre resumo gerado;
   informação mais nova prevalece somente quando não contradiz uma decisão humana.
5. Cite os títulos/IDs usados e declare incerteza quando houver conflito.

## Quando promover memória a conhecimento

Promova somente conteúdo reutilizável: decisões, arquitetura, procedimentos,
restrições, aprendizados, estado atual e contexto que altere uma ação futura.
Não promova saudações, chamadas de ferramenta, logs transitórios, tentativas
fracassadas sem aprendizado ou duplicatas.

Toda nota deve ter um assunto principal, título descritivo, `projeto`, `tipo`,
`status`, `sensibilidade`, `fonte`, pelo menos um link para o mapa do projeto e,
quando houver, links relacionados. Prefira atualizar uma nota existente.
Ao corrigir o projeto manualmente, defina `projeto_manual: true`; assim futuras
reclassificações automáticas preservam a decisão humana.

## Ciclo de qualidade e treino

`candidato → curado → verificado → aprovado_para_treino`

- Exportações automáticas começam como `candidato`; classificação automática não é validação.
- `curado` significa que forma, projeto, duplicidade e links foram revisados.
- `verificado` exige conferência com a fonte e ausência de contradição conhecida.
- Fine-tuning aceita apenas exemplos com `treino.aprovado: true`, `status: verificado`
  e `sensibilidade: publico`; conteúdo `interno` exige inclusão explícita. Nunca
  transforme uma nota comum em par instrução/resposta por suposição.
- Conhecimento factual atualizável deve alimentar RAG, não fine-tuning. Fine-tuning
  serve para padrões de comportamento, formato, decisão e uso de ferramentas.

## Escrita e segurança

- Dentro de `.animus/exported/`: o agente pode propor; só aplica com autorização
  explícita ou policy previamente concedida.
- Fora dessa pasta: nunca sobrescrever, mover ou renomear nota humana sem aprovação.
- Nunca copiar segredos, tokens, `.env`, credenciais ou dados pessoais desnecessários.
- Conflitos vão para `.animus/quarantine/`; não force sobrescrita.
- Após mudanças, regenere o catálogo, confira órfãos/duplicatas e registre o motivo.

## Funil de consulta

`Painel → mapa do projeto → animus_obsidian_search → animus_search → memória bruta`

Comece em [[.animus/exported/00 - Início|Início do Animus]].
"""


PROJECT_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Franquiaria & GIFT", "franquiaria-gift", ("franquiaria", "gift-app", "sistema gift", "gift bi")),
    ("Música Acessível", "musica-acessivel", ("música acessível", "musica acessivel", "musicaacessivel", "estanteorquestra", "ma.datano")),
    ("Atualizar Bases", "atualizar-bases", ("atualizar bases", "atualizarbases", "downloadengine", "tamanho.txt", "sharepointpowerpivot")),
    ("Ofertas & Dados Claro", "ofertas-dados-claro", ("atl / btl", "atl btl", "ofício 85", "oficio 85", "mcr_o", "ofertas_2023", "classificação de ofertas")),
    ("Microsoft Copilot Agents", "microsoft-copilot-agents", ("microsoftcopilotagents", "microsoft copilot agents", "microsoft 365 copilot", "agente persistente no excel")),
    ("IRobot", "irobot", ("irobot", "workflowengine", "orchestrationservice", "t-53", "t-61", "taol1_rpt", "benchmarkconfigservice", "ft_funil@p00dw1")),
    ("Animus", "animus", ("animus", "eagle vision", "desynchronize")),
    ("NPS Forge", "nps-forge", ("nps-forge", "nps forge", "npsforge", "nps-verbat", "glossario_dashboard", "verbatins jan")),
    ("Binance Bot", "binance-bot", ("binance", "oco", "pnl fee")),
    ("Redes & MikroTik", "redes-mikrotik", ("mikrotik", "wireguard", "rosssh", "failover wan", "rb 10.", "rb .")),
    ("Datano", "datano", ("datano-agents", "datano ecosystem", "datano-ecosystem", "security-audit")),
    ("xQuads", "xquads", ("xquads", "squads/", "agents library")),
    ("PyAccelerate", "pyaccelerate", ("pyaccelerate", "vulkaninfo", "_safe_run")),
    ("Workspace X", "workspace-x", ("workspace x", "x:\\", "irobot-not-dev")),
    ("Infraestrutura", "infraestrutura", ("zabbix", "termux", "debian gui", "vps hostinger", "setup distro", "huananzhi", "tpm")),
    ("Identidade profissional", "identidade-profissional", ("cv_guilherme", "github-identity", "user-profile", "tcc-paola")),
    ("Python & Ambientes", "python-ambientes", ("workspacepython", "repo-venv", "python environment")),
)


@dataclass
class ExportResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sanitize_title(title: str) -> str:
    # Windows-invalid plus Obsidian WikiLink-reserved characters.
    value = re.sub(r'[<>:"/\\|?*\[\]#^\x00-\x1f]', "-", title).strip(" .-")
    value = re.sub(r"\s+", " ", value)
    return value[:100].rstrip() or "memory"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _yaml_frontmatter(data: dict[str, Any]) -> str:
    dumped = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{dumped}\n---\n"


def _display_title(row: dict[str, Any], body: str, fallback: str) -> str:
    lowered_body = body.casefold()
    if "verbatins jan 2026" in lowered_body:
        return "NPS Forge — QA Verbatins Jan 2026"
    if "ft_funil@p00dw1" in lowered_body:
        return "Funil P00DW1 — ajustes e verificações"
    title = str(row.get("title") or "").strip()
    generic = {
        "plan", "notes", "task", "walkthrough", "implementation_plan",
        "repositorio_overview",
    }
    normalized = title.removeprefix("antigravity-memory:").removesuffix(".md")
    heading = re.search(r"^#{1,3}\s+([^\r\n]+)", body, flags=re.MULTILINE)
    if (not title or normalized.casefold() in generic or title.startswith("antigravity-memory:")) and heading:
        title = heading.group(1).strip()
    title = re.sub(r"\s+", " ", title or fallback)
    return title[:120].rstrip()


def _infer_project(row: dict[str, Any], body: str, metadata: dict[str, Any]) -> tuple[str, str]:
    explicit = str(metadata.get("projeto") or metadata.get("project") or "").strip()
    if explicit and metadata.get("projeto_manual") is True:
        return explicit, sanitize_title(explicit).casefold().replace(" ", "-")
    sample = " ".join((
        str(row.get("title") or ""),
        str(row.get("workspace") or ""),
        body[:12_000],
    )).casefold()
    for name, slug, needles in PROJECT_RULES:
        if any(needle.casefold() in sample for needle in needles):
            return name, slug
    return "Geral — revisar", "geral-revisar"


def _wikilink(relative: Path, label: str | None = None) -> str:
    target = relative.with_suffix("").as_posix()
    return f"[[{target}|{label}]]" if label else f"[[{target}]]"


def _project_map_path(project: str) -> Path:
    return Path(".animus/exported/Sistema/Projetos") / f"{sanitize_title(project)}.md"


def _knowledge_path(project: str, title: str, memory_id: str) -> Path:
    return (
        Path(".animus/exported/Conhecimento")
        / sanitize_title(project)
        / f"{sanitize_title(title)}--{memory_id[:8]}.md"
    )


def _sensitive_findings(text: str) -> list[str]:
    patterns = {
        "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        "provider_token": r"\b(?:sk|gh[opurs])_[A-Za-z0-9_-]{16,}",
        "assigned_secret": (
            r"(?i)\b(?:api[_-]?key|access[_-]?token|password|passwd|senha|secret)\b"
            r"\s*[:=]\s*[\"']?[A-Za-z0-9_./+\-=]{12,}"
        ),
    }
    return [name for name, pattern in patterns.items() if re.search(pattern, text)]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def initialize_vault(vault: ObsidianVaultConfig) -> None:
    """Create the managed layout and non-authoritative vault metadata."""
    root = vault.path.expanduser().resolve()
    managed = root / ".animus"
    for child in ("exported", "quarantine", "backups"):
        (managed / child).mkdir(parents=True, exist_ok=True)
    metadata = managed / "config.json"
    if not metadata.exists():
        _atomic_write(
            metadata,
            json.dumps(
                {
                    "vault": vault.name,
                    "managed_path": ".animus/exported",
                    "note": "Effective configuration remains in the Animus peer data directory.",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
    # Keep operational metadata out of Obsidian's Markdown index/graph.
    readme = managed / "README.txt"
    if not readme.exists():
        _atomic_write(
            readme,
            "# Animus managed area\n\n"
            "Files in `exported/` are managed by Animus. Conflicting generated notes "
            "are preserved in `quarantine/`; recoverable snapshots live in `backups/`; "
            "actions are recorded in `audit.jsonl`. Human notes outside this directory "
            "are never overwritten by the integration.\n",
        )


class ObsidianManager:
    """Enforce managed-folder, conflict, audit, backup, and rollback rules."""

    def __init__(self, config: AnimusConfig, engine: IndexEngine):
        self.config = config
        self.engine = engine

    def vault(self, name: str) -> ObsidianVaultConfig:
        for vault in self.config.obsidian_vaults:
            if vault.name == name:
                root = vault.path.expanduser().resolve()
                if not root.is_dir():
                    raise ValueError(f"vault path is unavailable: {root}")
                return vault.model_copy(update={"path": root})
        raise ValueError(f"unknown Obsidian vault: {name}")

    def export(
        self,
        vault_name: str,
        memory_ids: Iterable[str],
        *,
        dry_run: bool = False,
        actor: str = "cli",
        reason: str = "explicit export",
        destination_folder: str = ".animus/exported",
    ) -> ExportResult:
        vault = self.vault(vault_name)
        if not vault.export_enabled:
            raise PermissionError(f"export is disabled for vault '{vault.name}'")
        result = ExportResult(dry_run=dry_run)
        root = vault.path
        folder = Path(destination_folder.replace("\\", "/"))
        managed_root = (root / ".animus" / "exported").resolve()
        destination_root = (root / folder).resolve()
        if (
            folder.is_absolute()
            or ".." in folder.parts
            or (destination_root != managed_root and managed_root not in destination_root.parents)
        ):
            raise PermissionError("export destination must be inside .animus/exported")
        for memory_id in dict.fromkeys(memory_ids):
            row = self.engine.get_memory(memory_id)
            if not row:
                result.skipped.append(memory_id)
                continue
            relative = (
                folder / f"{sanitize_title(row.get('title') or 'memory')}--{memory_id[:8]}.md"
            )
            target = root / relative
            # A title can evolve while the memory identity stays stable.
            # Locate an earlier managed export by ID suffix so an edit does
            # not leave duplicate notes under the old and new titles.
            export_root = root / ".animus" / "exported"
            if export_root.is_dir():
                for candidate in export_root.rglob(f"*--{memory_id[:8]}.md"):
                    try:
                        candidate_meta, _, candidate_warning = parse_frontmatter(
                            candidate.read_text(encoding="utf-8")
                        )
                    except (OSError, UnicodeError):
                        continue
                    marker = candidate_meta.get("animus", {})
                    if (
                        not candidate_warning
                        and isinstance(marker, dict)
                        and marker.get("memory_id") == memory_id
                        and marker.get("managed") is True
                    ):
                        target = candidate
                        relative = candidate.relative_to(root)
                        break
            body = (row.get("content") or "").strip() + "\n"
            body_hash = _hash(body)
            frontmatter = {
                "animus": {
                    "memory_id": memory_id,
                    "source_type": row.get("type", ""),
                    "source_node": row.get("source_node", ""),
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "managed": True,
                    "content_hash": body_hash,
                }
            }
            rendered = _yaml_frontmatter(frontmatter) + "\n" + body
            action = "created"
            before = ""
            if target.exists():
                before = target.read_text(encoding="utf-8")
                existing_meta, existing_body, warning = parse_frontmatter(before)
                marker = existing_meta.get("animus", {}) if isinstance(existing_meta, dict) else {}
                if (
                    warning
                    or not isinstance(marker, dict)
                    or marker.get("managed") is not True
                    or marker.get("memory_id") != memory_id
                ):
                    conflict = self._quarantine(root, relative, rendered, memory_id, dry_run)
                    result.conflicts.append(str(conflict))
                    self._audit(
                        root,
                        actor,
                        reason,
                        memory_id,
                        str(relative),
                        "conflict",
                        before,
                        rendered,
                        dry_run,
                    )
                    continue
                recorded_hash = marker.get("content_hash")
                current_hash = _hash(existing_body.lstrip("\r\n").rstrip() + "\n")
                if recorded_hash and current_hash != recorded_hash:
                    conflict = self._quarantine(root, relative, rendered, memory_id, dry_run)
                    result.conflicts.append(str(conflict))
                    self._audit(
                        root,
                        actor,
                        reason,
                        memory_id,
                        str(relative),
                        "conflict",
                        before,
                        rendered,
                        dry_run,
                    )
                    continue
                if current_hash == body_hash:
                    result.unchanged.append(str(relative))
                    continue
                # Keep user/agent-added frontmatter (tags, aliases, project,
                # etc.) while replacing only Animus' authoritative marker.
                frontmatter = {**existing_meta, "animus": frontmatter["animus"]}
                rendered = _yaml_frontmatter(frontmatter) + "\n" + body
                action = "updated"
            if not dry_run:
                if before:
                    self._backup(root, relative, target)
                _atomic_write(target, rendered)
            getattr(result, action).append(str(relative))
            self._audit(
                root, actor, reason, memory_id, str(relative), action, before, rendered, dry_run
            )
        return result

    def build_catalog(
        self, vault_name: str, *, actor: str = "curator", install_style: bool = False
    ) -> dict[str, Any]:
        """Build the project-oriented knowledge workspace over managed exports."""
        vault = self.vault(vault_name)
        root = vault.path
        export_root = root / ".animus" / "exported"
        projects: dict[str, dict[str, Any]] = {}
        statuses: dict[str, int] = {}

        for note in list(export_root.rglob("*.md")):
            try:
                before = note.read_text(encoding="utf-8")
                metadata, body, warning = parse_frontmatter(before)
            except (OSError, UnicodeError):
                continue
            marker = metadata.get("animus", {}) if isinstance(metadata, dict) else {}
            memory_id = marker.get("memory_id") if isinstance(marker, dict) else None
            if warning or not memory_id:
                continue
            row = self.engine.get_memory(str(memory_id))
            if not row:
                continue

            project, slug = _infer_project(row, body, metadata)
            source = str(row.get("type") or "other")
            title = _display_title(row, body, note.stem.rsplit("--", 1)[0])
            desired_relative = _knowledge_path(project, title, str(memory_id))
            desired_note = root / desired_relative
            if note.resolve() != desired_note.resolve():
                desired_note.parent.mkdir(parents=True, exist_ok=True)
                if desired_note.exists():
                    raise FileExistsError(f"knowledge destination already exists: {desired_note}")
                old_relative = note.relative_to(root)
                os.replace(note, desired_note)
                self._audit(
                    root, actor, "migrate legacy knowledge layout", str(memory_id),
                    f"{old_relative.as_posix()} -> {desired_relative.as_posix()}",
                    "moved", before, before, False,
                )
                note = desired_note
            relative = note.relative_to(root)
            hub_relative = _project_map_path(project)
            status = str(metadata.get("status") or "candidato")
            if status not in {"candidato", "curado", "verificado", "depreciado"}:
                status = "candidato"
            statuses[status] = statuses.get(status, 0) + 1
            entry = projects.setdefault(
                slug, {"name": project, "slug": slug, "entries": [], "sources": {}}
            )
            entry["entries"].append({
                "title": title, "path": relative, "source": source,
                "workspace": row.get("workspace") or "sem-workspace",
                "memory_id": str(memory_id), "status": status,
            })
            entry["sources"][source] = entry["sources"].get(source, 0) + 1

            old_tags = metadata.get("tags", [])
            if isinstance(old_tags, str):
                old_tags = [old_tags]
            aliases = metadata.get("aliases", [])
            if not isinstance(aliases, list):
                aliases = []
            cssclasses = metadata.get("cssclasses", [])
            if not isinstance(cssclasses, list):
                cssclasses = []
            enriched = {
                **metadata,
                "aliases": list(dict.fromkeys([*aliases, title])),
                "tags": list(dict.fromkeys([
                    *old_tags, "animus", f"projeto/{slug}", f"fonte/{source}"
                ])),
                "projeto": project,
                "classificacao": "manual" if metadata.get("projeto_manual") is True else "automatica",
                "tipo": metadata.get("tipo") or "memoria-fonte",
                "status": status,
                "sensibilidade": metadata.get("sensibilidade") or "interno",
                "fonte": source,
                "mapa": _wikilink(hub_relative),
                "cssclasses": list(dict.fromkeys([*cssclasses, "animus-memory"])),
            }
            rendered = _yaml_frontmatter(enriched) + "\n" + body.lstrip("\r\n")
            if rendered != before:
                self._backup(root, relative, note)
                _atomic_write(note, rendered)
                self._audit(
                    root, actor, "classify knowledge candidate", str(memory_id),
                    relative.as_posix(), "updated", before, rendered, False,
                )

        guide_path = export_root / "Sistema" / "Guia dos Agentes.md"
        self._write_markdown_artifact(
            root, guide_path, AGENT_GUIDE,
            tags=["animus", "agentes", "governanca"], artifact="agent-guide",
            actor=actor, cssclass="animus-guide",
        )
        templates = self._write_templates(root, actor)
        for project in projects.values():
            self._write_project_map(root, project, actor)

        ordered = sorted(
            projects.values(), key=lambda item: (-len(item["entries"]), item["name"])
        )
        dashboard = export_root / "00 - Início.md"
        self._write_dashboard(root, dashboard, ordered, statuses, actor)
        count = sum(len(project["entries"]) for project in projects.values())
        canvas = export_root / "Sistema" / "Mapa de Conhecimento.canvas"
        self._write_plain_artifact(
            root, canvas,
            json.dumps(self._canvas_data(root, dashboard, guide_path, ordered), ensure_ascii=False, indent=2) + "\n",
            artifact="knowledge-canvas", actor=actor,
        )
        expected_artifacts = {
            dashboard.resolve(), guide_path.resolve(), canvas.resolve(),
            *(Path(root / path).resolve() for path in templates),
            *(Path(root / _project_map_path(project["name"])).resolve() for project in projects.values()),
        }
        self._remove_legacy_artifacts(root, export_root, expected_artifacts, actor)
        self._remove_empty_directories(export_root)
        style_installed = self._install_style(root, actor) if install_style else False
        return {
            "home": dashboard.relative_to(root).as_posix(),
            "canvas": canvas.relative_to(root).as_posix(),
            "guide": guide_path.relative_to(root).as_posix(),
            "templates": templates,
            "notes": count, "projects": len(projects), "statuses": statuses,
            "style_installed": style_installed,
        }

    def _write_templates(self, root: Path, actor: str) -> list[str]:
        folder = root / ".animus" / "exported" / "Modelos"
        knowledge = folder / "Modelo - Nota de Conhecimento.md"
        training = folder / "Modelo - Exemplo Fine-Tuning.md"
        knowledge_body = """# Título descritivo

## Resumo

Explique o conhecimento durável em poucas linhas.

## Evidências e origem

- Fonte:
- Data da verificação:

## Conhecimento aplicável

Registre decisão, procedimento, restrição ou arquitetura sem transcrição bruta.

## Relações

- Mapa do projeto:
- Notas relacionadas:
"""
        training_body = """# Exemplo de comportamento para fine-tuning

> [!warning] Aprovação
> Só defina `treino.aprovado: true` após revisar privacidade, correção e qualidade
> da instrução e da resposta ideal no frontmatter.

## Por que este exemplo representa o comportamento desejado?

Explique o padrão reutilizável. Fatos mutáveis pertencem ao RAG, não ao fine-tuning.
"""
        common = {
            "projeto": "PREENCHER", "projeto_manual": True,
            "classificacao": "manual", "status": "candidato",
            "sensibilidade": "interno", "fonte": "curadoria-humana",
        }
        self._write_markdown_artifact(
            root, knowledge, knowledge_body,
            tags=["animus", "modelo", "conhecimento"], artifact="knowledge-template",
            actor=actor, cssclass="animus-memory",
            extra={**common, "tipo": "PREENCHER"},
        )
        self._write_markdown_artifact(
            root, training, training_body,
            tags=["animus", "modelo", "fine-tuning"], artifact="sft-template",
            actor=actor, cssclass="animus-guide",
            extra={
                **common, "tipo": "exemplo",
                "treino": {
                    "aprovado": False, "sistema": "",
                    "instrucao": "PREENCHER", "resposta": "PREENCHER",
                },
            },
        )
        return [knowledge.relative_to(root).as_posix(), training.relative_to(root).as_posix()]

    def agent_guide(self, vault_name: str = "") -> str:
        """Return the canonical consultation, curation, and training contract."""
        suffix = ""
        if vault_name:
            vault = self.vault(vault_name)
            suffix = f"\n\nVault ativo: `{vault.name}` em `{vault.path}`."
        return AGENT_GUIDE + suffix

    def export_dataset(
        self, vault_name: str, *, kind: str = "rag", dry_run: bool = True,
        include_internal: bool = False, actor: str = "dataset-curator",
    ) -> dict[str, Any]:
        """Export only explicitly qualified gold notes as RAG or chat JSONL."""
        if kind not in {"rag", "sft"}:
            raise ValueError("dataset kind must be 'rag' or 'sft'")
        vault = self.vault(vault_name)
        root = vault.path
        records: list[dict[str, Any]] = []
        provenance: list[dict[str, str]] = []
        rejected = {
            "not_verified": 0, "sensitivity": 0, "secret_scan": 0,
            "not_approved": 0, "invalid_pair": 0,
        }
        allowed_sensitivity = {"publico", "público"}
        if include_internal:
            allowed_sensitivity.add("interno")
        for note in (root / ".animus" / "exported").rglob("*.md"):
            try:
                metadata, body, warning = parse_frontmatter(note.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
            marker = metadata.get("animus", {}) if isinstance(metadata, dict) else {}
            memory_id = marker.get("memory_id") if isinstance(marker, dict) else None
            if warning or not memory_id:
                continue
            if metadata.get("status") != "verificado":
                rejected["not_verified"] += 1
                continue
            if str(metadata.get("sensibilidade") or "interno").casefold() not in allowed_sensitivity:
                rejected["sensitivity"] += 1
                continue
            if _sensitive_findings(body):
                rejected["secret_scan"] += 1
                continue
            row = self.engine.get_memory(str(memory_id)) or {}
            title = _display_title(row, body, note.stem.rsplit("--", 1)[0])
            if kind == "rag":
                records.append({
                    "id": str(memory_id), "title": title, "text": body.strip(),
                    "metadata": {
                        "projeto": metadata.get("projeto", ""),
                        "tipo": metadata.get("tipo", ""),
                        "fonte": metadata.get("fonte", ""),
                        "tags": metadata.get("tags", []),
                    },
                })
            else:
                training = metadata.get("treino", {})
                if not isinstance(training, dict) or training.get("aprovado") is not True:
                    rejected["not_approved"] += 1
                    continue
                instruction = str(training.get("instrucao") or "").strip()
                response = str(training.get("resposta") or "").strip()
                if not instruction or not response:
                    rejected["invalid_pair"] += 1
                    continue
                messages = []
                system = str(training.get("sistema") or "").strip()
                if system:
                    messages.append({"role": "system", "content": system})
                messages.extend((
                    {"role": "user", "content": instruction},
                    {"role": "assistant", "content": response},
                ))
                records.append({"messages": messages})
            provenance.append({
                "record": str(len(records) - 1), "memory_id": str(memory_id),
                "path": note.relative_to(root).as_posix(),
            })

        output = root / ".animus" / "datasets" / f"{kind}.jsonl"
        manifest = output.with_suffix(".manifest.json")
        rendered = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records)
        manifest_data = {
            "kind": kind, "generated_at": datetime.now(timezone.utc).isoformat(),
            "records": len(records), "rejected": rejected,
            "include_internal": include_internal, "provenance": provenance,
        }
        if not dry_run:
            self._write_plain_artifact(
                root, output, rendered, artifact=f"{kind}-dataset", actor=actor
            )
            self._write_plain_artifact(
                root, manifest, json.dumps(manifest_data, ensure_ascii=False, indent=2) + "\n",
                artifact=f"{kind}-manifest", actor=actor,
            )
        return {
            "kind": kind, "dry_run": dry_run, "records": len(records),
            "rejected": rejected, "output": output.relative_to(root).as_posix(),
            "manifest": manifest.relative_to(root).as_posix(),
        }

    def search_knowledge(
        self, vault_name: str, query: str, *, project: str = "",
        include_candidates: bool = False, limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search verified human notes and governed managed exports in one vault."""
        vault = self.vault(vault_name)
        terms = [term for term in re.findall(r"[\wÀ-ÿ.-]+", query.casefold()) if len(term) > 1]
        if not terms:
            raise ValueError("knowledge search requires a meaningful query")
        allowed = {"verificado"}
        if include_candidates:
            allowed.update({"candidato", "curado"})
        results: list[dict[str, Any]] = []
        managed_root = (vault.path / ".animus" / "exported").resolve()
        notes: list[Path] = []
        for note in vault.path.rglob("*.md"):
            relative = note.relative_to(vault.path)
            if relative.parts and relative.parts[0] == ".animus":
                try:
                    note.resolve().relative_to(managed_root)
                except ValueError:
                    continue
            if any(part in {".obsidian", "attachments", "node_modules"} for part in relative.parts):
                continue
            notes.append(note)

        for note in notes:
            try:
                raw = note.read_text(encoding="utf-8")
                metadata, body, warning = parse_frontmatter(raw)
            except (OSError, UnicodeError):
                continue
            marker = metadata.get("animus", {}) if isinstance(metadata, dict) else {}
            managed_id = marker.get("memory_id") if isinstance(marker, dict) else None
            relative = note.relative_to(vault.path)
            memory_id = managed_id or note_id(vault.name, relative.as_posix())
            status = str(metadata.get("status") or "candidato")
            if warning or status not in allowed or _sensitive_findings(raw):
                continue
            note_project = str(metadata.get("projeto") or "")
            if project and project.casefold() not in note_project.casefold():
                continue
            alias_values = metadata.get("aliases", [])
            if not isinstance(alias_values, list):
                alias_values = [alias_values]
            aliases = " ".join(str(item) for item in alias_values)
            title = str(metadata.get("title") or (alias_values[0] if alias_values else ""))
            title = title or note.stem.rsplit("--", 1)[0]
            tag_values = metadata.get("tags", [])
            if not isinstance(tag_values, list):
                tag_values = [tag_values]
            header = f"{title} {aliases} {note_project} {' '.join(str(tag) for tag in tag_values)}".casefold()
            searchable = f"{header} {body.casefold()}"
            matched = [term for term in terms if term in searchable]
            if not matched:
                continue
            score = sum(header.count(term) * 5 + body.casefold().count(term) for term in matched)
            first = min((body.casefold().find(term) for term in matched if term in body.casefold()), default=0)
            start = max(0, first - 120)
            excerpt = re.sub(r"\s+", " ", body[start:start + 420]).strip()
            results.append({
                "memory_id": str(memory_id), "title": title,
                "project": note_project, "status": status,
                "sensitivity": metadata.get("sensibilidade", "interno"),
                "path": relative.as_posix(),
                "score": score, "excerpt": excerpt,
                "warning": "UNVERIFIED" if status != "verificado" else "",
            })
        results.sort(key=lambda item: (-item["score"], item["title"]))
        return results[:max(1, min(limit, 50))]

    def _write_project_map(self, root: Path, project: dict[str, Any], actor: str) -> None:
        entries = sorted(project["entries"], key=lambda item: item["title"].casefold())
        lines = [
            f"# {project['name']}", "", "> [!summary] Mapa do projeto",
            f"> {len(entries)} memórias candidatas/curadas. Confirme o status antes de usar.", "",
            "[[.animus/exported/00 - Início|← Início]] · "
            "[[.animus/exported/Sistema/Guia dos Agentes|Guia dos agentes]]", "",
            "## Conhecimento disponível", "",
        ]
        for item in entries:
            lines.append(
                f"- {_wikilink(item['path'], item['title'])} · **{item['status']}** · "
                f"`{item['source']}` · `{item['memory_id'][:8]}`"
            )
        lines.extend((
            "", "## Como aprofundar", "",
            "Se o mapa não bastar, use `animus_search` com o projeto e termos específicos. "
            "Valide decisões na fonte mais recente.", "",
        ))
        target = root / _project_map_path(project["name"])
        self._write_markdown_artifact(
            root, target, "\n".join(lines),
            tags=["animus", "mapa", f"projeto/{project['slug']}"],
            artifact="project-map", actor=actor, cssclass="animus-project-map",
            extra={"projeto": project["name"], "total_memorias": len(entries)},
        )

    def _write_dashboard(
        self, root: Path, target: Path, projects: list[dict[str, Any]],
        statuses: dict[str, int], actor: str,
    ) -> None:
        status_line = " · ".join(f"{key}: **{value}**" for key, value in sorted(statuses.items()))
        total = sum(statuses.values())
        lines = [
            "# Início — Animus", "", "> [!abstract] Knowledge OS",
            f"> **{total}** memórias · **{len(projects)}** projetos", f"> {status_line}", "",
            "[[.animus/exported/Sistema/Mapa de Conhecimento.canvas|🗺️ Abrir Canvas]] · "
            "[[.animus/exported/Sistema/Guia dos Agentes|🤖 Guia dos agentes]]", "",
            "[[.animus/exported/Modelos/Modelo - Nota de Conhecimento|📝 Nova nota]] · "
            "[[.animus/exported/Modelos/Modelo - Exemplo Fine-Tuning|🎯 Novo exemplo SFT]]", "",
            "## Pipeline de conhecimento", "",
            "```mermaid", "flowchart LR", "  A[Memória bruta] --> B[Candidato]",
            "  B --> C[Curado]", "  C --> D[Verificado]", "  D --> E[RAG Gold]",
            "  D -->|par instrução-resposta aprovado| F[Fine-tuning JSONL]", "```", "",
            "## Projetos", "",
        ]
        for project in projects:
            sources = " · ".join(
                f"{name}: {count}" for name, count in sorted(project["sources"].items())
            )
            hub = _project_map_path(project["name"])
            lines.extend((
                f"> [!animus-project]+ {project['name']} — {len(project['entries'])}",
                f"> {_wikilink(hub, 'Abrir mapa')} · {sources}", "",
            ))
        lines.extend((
            "## Regra rápida", "", "> [!tip] Consulta em camadas",
            "> Painel → projeto → nota verificada → busca MCP → memória bruta.",
            "> Exportado não significa validado. Nunca treine com candidatos.", "",
        ))
        self._write_markdown_artifact(
            root, target, "\n".join(lines), tags=["animus", "painel", "inicio"],
            artifact="dashboard", actor=actor, cssclass="animus-dashboard",
        )

    def _write_markdown_artifact(
        self, root: Path, target: Path, body: str, *, tags: list[str], artifact: str,
        actor: str, cssclass: str, extra: dict[str, Any] | None = None,
    ) -> None:
        body = body.rstrip() + "\n"
        metadata: dict[str, Any] = {
            "tags": tags, "cssclasses": [cssclass], **(extra or {}),
            "animus": {"managed": True, "artifact": artifact, "content_hash": _hash(body)},
        }
        self._write_plain_artifact(
            root, target, _yaml_frontmatter(metadata) + "\n" + body,
            artifact=artifact, actor=actor,
        )

    def _remove_legacy_artifacts(
        self, root: Path, export_root: Path, expected: set[Path], actor: str
    ) -> None:
        generated = {
            "catalog", "dashboard", "agent-guide", "project-map",
            "knowledge-template", "sft-template",
        }
        for note in export_root.rglob("*.md"):
            if note.resolve() in expected:
                continue
            try:
                before = note.read_text(encoding="utf-8")
                metadata, _, warning = parse_frontmatter(before)
            except (OSError, UnicodeError):
                continue
            marker = metadata.get("animus", {}) if isinstance(metadata, dict) else {}
            artifact = marker.get("artifact") if isinstance(marker, dict) else None
            if not warning and marker.get("managed") is True and artifact in generated:
                relative = note.relative_to(root)
                note.unlink()
                self._audit(
                    root, actor, "remove legacy generated artifact", str(artifact),
                    relative.as_posix(), "deleted", before, "", False,
                )
        for canvas in export_root.rglob("*.canvas"):
            if canvas.resolve() not in expected:
                before = canvas.read_text(encoding="utf-8")
                relative = canvas.relative_to(root)
                canvas.unlink()
                self._audit(
                    root, actor, "remove legacy canvas", "knowledge-canvas",
                    relative.as_posix(), "deleted", before, "", False,
                )
        legacy_readme = root / ".animus" / "README.md"
        if legacy_readme.exists():
            legacy_readme.unlink()

    @staticmethod
    def _remove_empty_directories(root: Path) -> None:
        for directory in sorted(
            (path for path in root.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts), reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass

    def _write_plain_artifact(
        self, root: Path, target: Path, rendered: str, *, artifact: str, actor: str
    ) -> None:
        before = target.read_text(encoding="utf-8") if target.exists() else ""
        if before == rendered:
            return
        relative = target.relative_to(root)
        if before:
            self._backup(root, relative, target)
        _atomic_write(target, rendered)
        self._audit(
            root, actor, f"rebuild {artifact}", artifact, relative.as_posix(),
            "updated" if before else "created", before, rendered, False,
        )

    def _canvas_data(
        self, root: Path, dashboard: Path, guide: Path, projects: list[dict[str, Any]]
    ) -> dict[str, Any]:
        def node_id(value: str) -> str:
            return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
        dashboard_rel = dashboard.relative_to(root).as_posix()
        guide_rel = guide.relative_to(root).as_posix()
        center = node_id(dashboard_rel)
        nodes: list[dict[str, Any]] = [
            {"id": center, "type": "file", "file": dashboard_rel, "x": 0, "y": 0, "width": 360, "height": 240},
            {"id": node_id(guide_rel), "type": "file", "file": guide_rel, "x": 0, "y": 300, "width": 360, "height": 220, "color": "4"},
        ]
        edges: list[dict[str, Any]] = []
        for index, project in enumerate(projects):
            relative = _project_map_path(project["name"]).as_posix()
            project_id = node_id(relative)
            nodes.append({
                "id": project_id, "type": "file", "file": relative,
                "x": 500 + (index % 3) * 390, "y": (index // 3) * 230,
                "width": 330, "height": 180, "color": str((index % 6) + 1),
            })
            edges.append({
                "id": node_id(f"{center}:{project_id}"), "fromNode": center,
                "fromSide": "right", "toNode": project_id, "toSide": "left",
                "label": f"{len(project['entries'])} memórias",
            })
        return {"nodes": nodes, "edges": edges}

    def _install_style(self, root: Path, actor: str) -> bool:
        obsidian = root / ".obsidian"
        if not obsidian.is_dir():
            return False
        css = """/* Animus Knowledge OS */
.callout[data-callout="animus-project"] { --callout-color: 123, 97, 255; --callout-icon: lucide-orbit; }
.animus-dashboard h1, .animus-project-map h1 { color: var(--interactive-accent); }
.animus-dashboard .callout[data-callout="animus-project"] { border-radius: 14px; box-shadow: 0 4px 18px rgba(0,0,0,.12); }
.animus-memory .metadata-container { border-left: 3px solid var(--interactive-accent); padding-left: 12px; }
.animus-guide .callout[data-callout="important"] { border-width: 2px; }
"""
        snippet = obsidian / "snippets" / "animus.css"
        self._write_plain_artifact(root, snippet, css, artifact="obsidian-style", actor=actor)
        appearance = obsidian / "appearance.json"
        before = appearance.read_text(encoding="utf-8") if appearance.exists() else "{}\n"
        try:
            data = json.loads(before)
        except json.JSONDecodeError:
            return False
        enabled = data.get("enabledCssSnippets", [])
        if not isinstance(enabled, list):
            enabled = []
        if "animus" not in enabled:
            data["enabledCssSnippets"] = [*enabled, "animus"]
            self._write_plain_artifact(
                root, appearance, json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                artifact="obsidian-appearance", actor=actor,
            )
        return True

    def quarantine_exports(
        self, vault_name: str, memory_ids: Iterable[str], *, reason: str, actor: str = "curator"
    ) -> list[str]:
        """Move managed exports out of the knowledge graph without deleting them."""
        vault = self.vault(vault_name)
        root = vault.path
        moved: list[str] = []
        for memory_id in dict.fromkeys(memory_ids):
            for source in (root / ".animus" / "exported").rglob(f"*--{memory_id[:8]}.md"):
                metadata, _, warning = parse_frontmatter(source.read_text(encoding="utf-8"))
                marker = metadata.get("animus", {}) if isinstance(metadata, dict) else {}
                if warning or not isinstance(marker, dict) or marker.get("memory_id") != memory_id:
                    continue
                destination = (
                    root / ".animus" / "quarantine" / "curadoria"
                    / f"{source.name}.quarantine"
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    destination = destination.with_name(
                        f"{destination.stem}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                        f"{destination.suffix}"
                    )
                before = source.read_text(encoding="utf-8")
                os.replace(source, destination)
                relative = destination.relative_to(root).as_posix()
                moved.append(relative)
                self._audit(
                    root, actor, reason, memory_id, relative, "quarantined", before, before, False
                )
                break
        return moved

    def propose_organization(
        self,
        vault_name: str,
        memory_ids: Iterable[str],
        *,
        folder: str = ".animus/exported",
        actor: str = "agent",
        reason: str = "organize memories",
    ) -> dict[str, Any]:
        vault = self.vault(vault_name)
        normalized = Path(folder.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("folder must be a relative path inside the vault")
        managed = normalized.parts[:2] == (".animus", "exported")
        operations = []
        for memory_id in dict.fromkeys(memory_ids):
            row = self.engine.get_memory(memory_id)
            if not row:
                continue
            destination = (
                normalized / f"{sanitize_title(row.get('title') or 'memory')}--{memory_id[:8]}.md"
            )
            operations.append(
                {
                    "operation": "export",
                    "memory_id": memory_id,
                    "source": row.get("source_path") or f"animus://memory/{memory_id}",
                    "destination": destination.as_posix(),
                    "reason": reason,
                    "risk": "low" if managed else "protected",
                }
            )
        request_raw = json.dumps([vault.name, actor, reason, operations], sort_keys=True)
        return {
            "request_id": hashlib.sha256(request_raw.encode()).hexdigest()[:16],
            "mode": "propose",
            "vault": vault.name,
            "actor": actor,
            "managed_scope": managed,
            "operations": operations,
        }

    def apply_organization(
        self, proposal: dict[str, Any], *, approved: bool, dry_run: bool = False
    ) -> ExportResult:
        if not approved:
            raise PermissionError("organization apply requires explicit approval")
        if not proposal.get("managed_scope"):
            raise PermissionError("organization can only write inside .animus/exported")
        ids = [
            op["memory_id"]
            for op in proposal.get("operations", [])
            if op.get("operation") == "export"
        ]
        return self.export(
            proposal["vault"],
            ids,
            dry_run=dry_run,
            actor=proposal.get("actor", "agent"),
            reason=f"organization {proposal.get('request_id', '')}",
        )

    def rollback_last(self, vault_name: str) -> str:
        vault = self.vault(vault_name)
        audit_path = vault.path / ".animus" / "audit.jsonl"
        if not audit_path.exists():
            raise ValueError("no audit log found")
        records = [
            json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line
        ]
        record = next(
            (r for r in reversed(records) if r.get("backup") or r.get("action") == "created"), None
        )
        if not record:
            raise ValueError("no recoverable operation found")
        target = (vault.path / record["path"]).resolve()
        if vault.path not in target.parents or not target.is_file():
            raise ValueError("invalid or missing rollback target")
        if record.get("action") == "created":
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            archived = (
                vault.path / ".animus" / "backups" / stamp
                / f"{record['path']}.bak"
            )
            archived.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, archived)
        else:
            backup = (vault.path / record["backup"]).resolve()
            if vault.path not in backup.parents or not backup.is_file():
                raise ValueError("invalid or missing backup")
            _atomic_write(target, backup.read_text(encoding="utf-8"))
        self._audit(
            vault.path,
            "cli",
            "rollback",
            record["memory_id"],
            record["path"],
            "rollback",
            "",
            "",
            False,
        )
        return record["path"]

    def _quarantine(
        self, root: Path, relative: Path, rendered: str, memory_id: str, dry_run: bool
    ) -> Path:
        target = (
            root / ".animus" / "quarantine"
            / f"{relative.stem}--conflict-{memory_id[:8]}.quarantine"
        )
        if target.exists():
            target = target.with_name(
                f"{target.stem}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.quarantine"
            )
        if not dry_run:
            _atomic_write(target, rendered)
        return target.relative_to(root)

    def _backup(self, root: Path, relative: Path, target: Path) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = root / ".animus" / "backups" / stamp / f"{relative.as_posix()}.bak"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        return backup.relative_to(root).as_posix()

    def _audit(
        self,
        root: Path,
        actor: str,
        reason: str,
        memory_id: str,
        path: str,
        action: str,
        before: str,
        after: str,
        dry_run: bool,
    ) -> None:
        if dry_run:
            return
        backup = ""
        if before and action == "updated":
            # The actual backup is already present; resolve the newest matching one.
            candidates = list((root / ".animus" / "backups").glob(f"*/{path}.bak"))
            if candidates:
                backup = (
                    max(candidates, key=lambda p: p.stat().st_mtime).relative_to(root).as_posix()
                )
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "reason": reason,
            "memory_id": memory_id,
            "path": path,
            "action": action,
            "before_hash": _hash(before) if before else "",
            "after_hash": _hash(after) if after else "",
            "backup": backup,
        }
        audit = root / ".animus" / "audit.jsonl"
        audit.parent.mkdir(parents=True, exist_ok=True)
        with audit.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
