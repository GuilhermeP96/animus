# PRs e issues abertas — revisão de 2026-11-01

Escopo: três issues e uma PR abertas, com descrições/comentários conferidos
no GitHub e comparação com a fonte atual. Revisão não significa encerramento
automático, instalação ou nova release.

| Referência | Evidência | Resultado |
| --- | --- | --- |
| [PR #9](https://github.com/GuilhermeP96/animus/pull/9) | A master não apresentava os campos seguros de motivo/backoff já oferecidos pelo engine | Integrado o patch original de 15 linhas, sua documentação e regressões. Somente códigos allowlisted e inteiro não negativo; SQL, caminhos e exceções não atravessam o MCP |
| [#8](https://github.com/GuilhermeP96/animus/issues/8) | Release 0.8.15 publicada e instalada nos dois peers ativos; RECORD, fonte, preservação e MCP configurado comprovados | Critério de fechamento atendido: 16 ferramentas e stats frescas em Windows/VPS; [aceite e limitações](ROLLOUT_0.8.15_20261101.md). O diagnóstico não promete eliminar todo timeout futuro |
| [#10](https://github.com/GuilhermeP96/animus/issues/10) | Loader e Siteverify integram a fonte e há evidência de renderização do SDK | Aceite humano com token real e replay continua pendente; não substituído por mocks ou health |
| [#2](https://github.com/GuilhermeP96/animus/issues/2) | Gate local e remoção de Dependabot estão presentes, mas as evidências de dependências e automações têm datas/escopos diferentes | Manter aberta para reconciliação do artefato e cobertura de validação operacional |

Validação da integração: 52 testes de MCP, federação e engine SQLite passaram
no ambiente Windows preparado. O grupo inclui as regressões originais da PR,
com estatísticas cold/stale e sanitização dos campos. O teste não consulta
memórias produtivas nem modifica SQL, cache, orçamento ou políticas de retry.

Esta entrega integra fonte na master preservando a AGPL e mudanças posteriores.
Não publica outro artefato 0.8.14, não reinstala peers e não reinicia MCPs. O
runtime instalado permanece distinto do código integrado. Distribuir a mudança
exige próxima versão imutável e teste do consumidor pelo fluxo existente.

A integração original da PR é ancestral da master. O retarget da PR para
master foi recusado pelo GitHub por não haver commits novos entre as linhas.
Após autorização explícita do proprietário para encerrar pendências
comprovadas, a PR #9 foi encerrada quanto à integração de fonte, com essa
distinção registrada na descrição. Não houve merge adicional na base antiga.
O encerramento não equivale a distribuição ou qualificação do wheel produtivo;
a issue #8 permaneceu aberta para essa próxima etapa, concluída depois na
[release 0.8.15](ROLLOUT_0.8.15_20261101.md). Os parágrafos anteriores descrevem
a integração de fonte anterior à distribuição.
