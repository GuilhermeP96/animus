# PRs e issues abertas — revisão de 2026-11-01

Escopo: três issues e uma PR abertas, com descrições/comentários conferidos
no GitHub e comparação com a fonte atual. Revisão não significa encerramento
automático, instalação ou nova release.

| Referência | Evidência | Resultado |
| --- | --- | --- |
| [PR #9](https://github.com/GuilhermeP96/animus/pull/9) | A master não apresentava os campos seguros de motivo/backoff já oferecidos pelo engine | Integrado o patch original de 15 linhas, sua documentação e regressões. Somente códigos allowlisted e inteiro não negativo; SQL, caminhos e exceções não atravessam o MCP |
| [#8](https://github.com/GuilhermeP96/animus/issues/8) | Comentários registram wheel antigo/RECORD e correspondência parcial com a fonte, mas stats ficaram indisponíveis em consulta real | Manter aberta. O diagnóstico não resolve o timeout; próxima versão imutável, qualificação do consumidor e disponibilidade continuam pendentes |
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
