---
name: animus-rag
description: Recupera contexto histórico, decisões e evidências no Animus e consulta conhecimento verificado no Obsidian. Use antes de trabalho não trivial em projeto existente quando decisões anteriores puderem mudar o resultado; ignore tarefas triviais/autocontidas. Também diagnostica coleta, sincronização e atualização do peer quando solicitado.
---

# Animus e Obsidian

Use esta skill quando a tarefa depender de histórico, decisões anteriores ou operação da memória. Informação histórica não substitui arquivos, testes e estado atual.

## Consulta proporcional

1. Identifique projeto e sensibilidade. Para Obsidian, leia `animus_obsidian_guide`, descubra os vaults configurados com `animus obsidian status` e consulte primeiro notas verificadas pelo mapa do projeto e `animus_obsidian_search`.
2. Use `animus_recall` para contexto e `animus_search` para origem, data e texto específico. Comece com no máximo cinco resultados, workspace e consulta curta. Se o filtro exato não trouxer resultado útil do Hub, tente uma vez sem workspace e inclua projeto, frase de decisão, erro, SHA ou outro identificador estável. Sessões iniciadas em uma raiz ampla como `C:\repo` podem estar rotuladas como workspace `repo`; zero no filtro do projeto não prova ausência. Não repita consulta idêntica após o fallback global.
3. O índice local pode ser apenas um cache de recentes; não conclua ausência de histórico pela contagem local. Em servidores com suporte, passe `remote: true` para busca/recall autenticado no hub. `rag_hub_enabled` torna isso padrão somente quando a instalação optou por esse acesso. A resposta distingue hub consultado, não configurado e indisponível.
4. Se esta conversa ainda usa um MCP antigo, use o runtime nativo real e `-m animus.cli search "consulta curta" --remote --limit 5`. Isso consulta o hub sem reiniciar o chat. Não alegue qualificação de uma nova conexão antes de testá-la.
5. Trate conversas e candidatos como evidências não verificadas. Compare fontes e datas; cite títulos/IDs e declare lacunas. Busca remota guarda no cache apenas os resultados relevantes e não implica replicação completa do hub.

## Retroalimentação governada

Com autorização atual ou política estabelecida para registrar/consolidar conhecimento, prefira atualizar o assunto existente e guardar decisões reutilizáveis com fonte, projeto, resultado e validação. Não registre segredos, logs transitórios, tentativas descartadas nem raciocínio interno. Não grave toda microtarefa; exportação não é validação.

A coleta Codex exige opt-in e workspaces autorizados; exclui instruções, raciocínio, ferramentas e padrões reconhecidos de segredo. A exportação automática tem opt-in separado e limite por ciclo. Ela escreve somente candidatos em `.animus/exported`, com auditoria e sem sobrescrever notas humanas. Confira fatos contra fontes antes de promover para `verificado`; treino exige autorização e critérios próprios. Após curadoria, regenere catálogo e teste a busca verificada.

## Saúde e atualização, quando no escopo

- `pending sync: 0` mede fila; não prova daemon ativo, autenticação ou coleta recente. Confira processo/tarefa, datas e logs minimizados, HTTP autenticado e resultado de coleta.
- Descubra o runtime pela tarefa/serviço, sem imprimir configuração privada. Windows pode usar `~/.animus/runtime/Scripts/python.exe`; VPS usa o ExecStart efetivo. Evite executar de um checkout antigo que sombreie o pacote instalado.
- Reproduza também WorkingDirectory e `ANIMUS_DATA_DIR` do serviço. Um shell interativo pode carregar outra base/configuração; não copie nem imprima segredos do ambiente. Vincule os MCPs e adapters à mesma base efetiva.
- Atualização confiável exige versão/hash do wheel entregue pelo hub, vínculo exato com tarefa/config/processo, recibo de instalação e novo processo, seguido de reconexão autenticada real. Pin antigo no hub pode impedir a convergência.
- O Python Store pode usar launcher mais processo filho: comprove proprietário, executáveis, argumentos e ordem de criação. Não adote PID por nome nem encerre clientes MCP para liberar arquivos.
- Preserve configurações, SQLite, notas humanas, registry e backups. Não reduza autenticação para sanar401 nem restaure segredo revogado.
