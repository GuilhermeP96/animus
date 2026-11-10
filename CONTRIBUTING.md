# Contribuir com o Animus

Criado e mantido por Guilherme Pinheiro, no ecossistema Datano.

Abra uma issue com uma reprodução mínima antes de propor mudanças extensas.
Envie pull requests focados, com descrição do problema, alteração e validação.
Execute os testes relevantes com `python -m pytest tests/<arquivo>` em um
ambiente isolado. Não use dados reais, colete históricos nem conecte um hub
pessoal ou corporativo para testar uma contribuição.

Para a suíte completa, use `python scripts/ci/validate.py` no ambiente de
desenvolvimento preparado. O executor isola perfis, dados de provedores e
fixtures; no Windows, verifica ACLs reais nos testes nativos. Skips de plataforma
e de privilégio para symlinks são explícitos. Consulte
[a qualificação Windows](docs/WINDOWS-SUITE-VALIDATION.md).

Novas contribuições devem ser de sua autoria ou ter origem e licença
compatíveis documentadas. Elas são recebidas sob AGPL-3.0-only, preservando
os direitos dos respectivos autores; contribuir não transfere copyright.
Preserve atribuições e identifique alterações conforme a licença.
Consulte LICENSE, NOTICE e TRADEMARKS.md.

Nunca inclua segredos, arquivos `.env`, bancos de memórias, transcrições,
configurações de peers, logs reais ou dados de clientes. Use exemplos
sintéticos. Vulnerabilidades e credenciais expostas seguem SECURITY.md.
