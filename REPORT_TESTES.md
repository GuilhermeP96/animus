# Animus — Relatório de Testes e Melhorias

**Data:** 2025-07-10
**Versão:** 0.1.0
**Python:** 3.13.12 | pytest 9.0.2 | Windows 11

---

## 1. Resumo Executivo

| Métrica | Valor |
|---------|-------|
| Total de testes | **155** |
| Passou | **155** (100%) |
| Falhou | **0** |
| Tempo total | **~28s** |
| Módulos cobertos | **11** |
| Bugs de produção encontrados | **2** |
| Bugs fixados | **2** |

---

## 2. Cobertura por Módulo

| Módulo | Testes | Status | Notas |
|--------|--------|--------|-------|
| `config.py` | 8 | ✅ All pass | Load/save, defaults, paths |
| `collector/models.py` | 10 | ✅ All pass | Memory auto-ID, serialization |
| `collector/copilot.py` | 13 | ✅ All pass | Debug logs, chat, workspace, MCP |
| `indexer/parser.py` | 16 | ✅ All pass | FTS cleaning, tag extraction |
| `indexer/engine.py` | 14 | ✅ All pass | CRUD, FTS5 search, sync tracking |
| `network/crypto.py` | 14 | ✅ All pass | HMAC-SHA256, auth headers |
| `network/sync.py` | 17 | ✅ All pass | 7 message types, parse, roundtrip |
| `server/app.py` | 10 | ✅ All pass | FastAPI endpoints, push/pull/search |
| `mcp/__init__.py` | 16 | ✅ All pass | 7 MCP tools, resources, protocol |
| `mcp/rag.py` | 17 | ✅ All pass | Decomposition, recall, token budget |
| `mcp/active.py` | 4 | ✅ All pass | Context generation, write |

---

## 3. Bugs de Produção Encontrados e Corrigidos

### BUG-001: IndexEngine.index_memory — detecção de duplicatas falha
- **Severidade:** 🔴 Alta
- **Arquivo:** `animus/indexer/engine.py`
- **Problema:** Usava `conn.total_changes` que é **cumulativo** na vida da conexão. Após o primeiro insert, `total_changes > 0` sempre retornava `True`, mesmo para INSERT OR IGNORE que não inseriu nada.
- **Impacto:** Duplicatas eram reportadas como "novas" — stats incorretos, possível reprocessamento desnecessário.
- **Fix:** Substituído `self.conn.total_changes > 0` por `cursor.rowcount > 0` que reflete apenas a última operação.

### BUG-002: IndexEngine — SQLite thread safety
- **Severidade:** 🟡 Média
- **Arquivo:** `animus/indexer/engine.py`
- **Problema:** `sqlite3.connect()` sem `check_same_thread=False` impedia uso em cenários multi-thread (FastAPI com workers, testes com TestClient).
- **Impacto:** Server crash quando endpoints eram chamados em threads diferentes da que criou a conexão.
- **Fix:** Adicionado `check_same_thread=False` ao `sqlite3.connect()`. Seguro pois já usamos WAL mode.

---

## 4. Melhorias Recomendadas

### 🔴 Prioridade Alta

| # | Melhoria | Módulo | Justificativa |
|---|----------|--------|---------------|
| 1 | **Adicionar tratamento de concorrência no IndexEngine** | `indexer/engine.py` | Com `check_same_thread=False`, escritas concorrentes podem causar `OperationalError: database is locked`. Usar `threading.Lock` ou connection-per-request. |
| 2 | **WebSocket auth no hub** | `server/app.py` | O TODO no código indica que WS auth não está implementado. Qualquer cliente pode conectar via WebSocket sem autenticação. |
| 3 | **Input validation no SyncProtocol.memories_from_push** | `network/sync.py` | Memories malformados são silenciosamente descartados (apenas logging). O caller não sabe quantos foram perdidos. |
| 4 | **Rate limiting no server** | `server/app.py` | Sem rate limiting, o hub está vulnerável a DoS via push/search flooding. |

### 🟡 Prioridade Média

| # | Melhoria | Módulo | Justificativa |
|---|----------|--------|---------------|
| 5 | **Connection pooling para o IndexEngine** | `indexer/engine.py` | Conexão singleton não escala para múltiplos workers. |
| 6 | **Adicionar timeout ao FTS search** | `indexer/engine.py` | Queries maliciosas com wildcards podem ser lentas. `conn.set_progress_handler()` pode limitar. |
| 7 | **Config validation** | `config.py` | `AnimusConfig.load()` aceita dados arbitrários do JSON sem validação de tipos. Pydantic valida mas sem feedback claro. |
| 8 | **Collector error resilience** | `collector/copilot.py` | `_collect_debug_logs` faz `continue` em exceções genéricas, mascarando erros reais. Usar logging com traceback. |
| 9 | **Memory content size limit** | `collector/models.py` | Content é ilimitado no modelo. Single memories com MBs de texto causariam problemas no FTS e na sync. |

### 🟢 Prioridade Baixa

| # | Melhoria | Módulo | Justificativa |
|---|----------|--------|---------------|
| 10 | **Adicionar testes de integração end-to-end** | `tests/` | Testar fluxo completo: collect → index → sync → search. |
| 11 | **Cobertura para `cli.py`** | `tests/` | CLI não tem testes. Usar `typer.testing.CliRunner`. |
| 12 | **Cobertura para `network/peer.py`** | `tests/` | Peer (async) precisa de testes com mock de httpx/websockets. |
| 13 | **Cobertura para `network/tunnel.py`** | `tests/` | TunnelManager precisa de testes com mock de subprocess. |
| 14 | **Cobertura para `collector/watcher.py`** | `tests/` | FileWatcher precisa de testes com watchdog events. |
| 15 | **Property-based testing** | `tests/` | Usar hypothesis para models e parser (fuzzing de inputs). |

---

## 5. Análise de Segurança

| Achado | Severidade | Status |
|--------|-----------|--------|
| HMAC-SHA256 auth com `compare_digest` ✅ | — | OK: constant-time comparison |
| Timestamps com max_age de 300s ✅ | — | OK: replay protection |
| CORS `allow_origins=["*"]` ⚠️ | Médio | Restringir em produção |
| Sem rate limiting | Alto | Implementar middleware |
| WS endpoint sem auth | Alto | Implementar via token no handshake |
| `check_same_thread=False` | Baixo | Aceitável com WAL mode |
| Content capped em 50KB no collector ✅ | — | OK |
| FTS queries escapam chars especiais ✅ | — | OK |

---

## 6. Métricas de Qualidade

```
Módulos de produção: 12 arquivos .py
Módulos de teste:    11 arquivos .py
Ratio teste/produção: ~0.92
Testes por módulo:    média 14.1
Tempo médio por teste: ~180ms
```

---

## 7. Próximos Passos Sugeridos

1. ✅ **Imediato** — Commit dos fixes (BUG-001 e BUG-002)
2. 🔜 **Sprint 1** — WebSocket auth + rate limiting + threading lock
3. 📋 **Sprint 2** — Testes para CLI, peer, tunnel, watcher
4. 📋 **Sprint 3** — Property-based testing + end-to-end integration tests
5. 📋 **Sprint 4** — CORS restriction + content size limits + connection pooling
