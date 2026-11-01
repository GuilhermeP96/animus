# Animus 0.8.15 — aceite da issue #8

A release [v0.8.15](https://github.com/GuilhermeP96/animus/releases/tag/v0.8.15)
distribui a correção da PR #9 a partir do commit
`c1dc56f77a2ad3cbf53fcfebd9a28399cde95967`. O wheel publicado e baixado
do hub autenticado nos dois peers tem SHA-256
`eae88d7cb1dd12c16a7b2f5bc61dd57b1b7c75bfd80c187cf8160c5290e6f78a`.
O readback dos três assets GitHub coincide com os arquivos publicados.

Os peers nativos Windows e VPS instalaram 0.8.15 pelo updater existente.
O Windows produziu receipt de instalação/restart verificados e a VPS retomou
seu serviço. Ambos aparecem online no hub com 0.8.15, passaram em HTTP HMAC
autenticado, `pip check`, RECORD instalado e comparação de 57 arquivos com o
wheel. A QA independente comparou os 37 Python à fonte versionada e validou
instalação, atualização preservando fixture e reinstalação idempotente.
O teste com interrupção SQLite real confirmou a apresentação segura do motivo
e dos 30 segundos de backoff. A suíte completa passou em 445 testes, com
5 skips de plataforma e 15 subtestes aprovados.

Novas conexões stdio executaram exatamente os comandos/configurações MCP
existentes em cada host: 16 ferramentas e estatísticas frescas, 1.718 memórias
no Windows e 229.755 na VPS. A consulta VPS levou 851 ms no total, com idade
da estatística de 0,618 s. O limite SQL permaneceu inalterado. A indisponibilidade
histórica não se repetiu nesses probes; isso não elimina a possibilidade de
timeout sob outras condições. A versão fixa 0.1.0 do handshake legado foi
registrada separadamente da versão 0.8.15 comprovada nos arquivos/metadados.
Nenhum processo MCP de chat aberto foi encerrado ou declarado recarregado.

Backups SQLite consistentes, configurações, registry, tarefa Windows, wheel
0.8.14 e imagem anterior foram preservados em áreas privadas. Comparação com
os backups encontrou zero memórias ausentes e zero alterações de conteúdo,
título, identidade, workspace ou metadados de origem. As configurações dos
peers e do hub permanecem idênticas em bytes. A retomada da sincronização
atualizou timestamps e ordem de tags de 21 notas Obsidian nos peers; conteúdo,
metadados e conjunto de tags dessas notas permanecem iguais. Não se afirma
que a base ativa permaneceu idêntica em bytes durante a coleta normal.

O hub está healthy na nova imagem e preserva volumes/chaves. Os containers e
imagens de Datano, Academy e fiscal permaneceram iguais e saudáveis; a raiz
pública da Datano e `/animus` responderam HTTP 200. Nenhuma emissão fiscal,
alteração de credenciais ou migração foi executada.

O aceite cobre os dois peers ativos observados. Uma identidade provisionada
sem conexão observada não é declarada atualizada. Máquina limpa, reboot real,
outros transports e disponibilidade sustentada ficam fora desta comprovação.
As evidências sanitizadas estão em
[release-0.8.15-20261101.json](evidence/release-0.8.15-20261101.json).
GitHub Actions continua desabilitado; o check `update-pip-graph` não substitui
os testes executados na VPS. O rollback preserva artefatos/dados anteriores;
não restaura credenciais revogadas nem altera notas humanas.
