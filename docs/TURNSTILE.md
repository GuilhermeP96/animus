# Turnstile no login humano — Animus

O login humano exige Cloudflare Turnstile managed antes de verificar credenciais
e emitir sessão. APIs de máquina, integrações e verificações de sessões existentes
mantêm seu mecanismo de autenticação. Não há dependência de Google/reCAPTCHA.

Configure no ambiente privado (`deployment protected environment`):

```dotenv
TURNSTILE_SITE_KEY=<chave pública do widget>
TURNSTILE_SECRET_KEY=<segredo protegido>
TURNSTILE_HOSTNAMES=animus.datano.com.br
```

`TURNSTILE_SECRET` também é aceito quando `TURNSTILE_SECRET_KEY` está ausente.
Configure o widget para o hostname exato da implantação. A ausência de configuração
ou indisponibilidade de Siteverify bloqueia o login com HTTP 503; tokens ausentes,
inválidos, expirados ou repetidos recebem HTTP 403. A resposta deve conter
`success === true`, `action=login`, hostname exato e timestamp de até cinco minutos.
O limite do token é 2048 caracteres, com timeout de oito segundos no transporte.
Não há opção de desativação em produção nem fallback permissivo.

O SDK oficial é carregado diretamente de `challenges.cloudflare.com`; o widget
é renderizado explicitamente e reiniciado após cada tentativa. Expiração e erro
do SDK preservam campos e permitem nova tentativa. Tokens ficam somente em
memória. O formulário contém aviso e links para privacidade e termos aplicáveis.

O evento `load` do SDK `async/defer` confirma a presença de `render` e libera
o widget diretamente. A fixture lança o erro 3857 se `ready()` for chamado
nesse modo. Renderização, reset, expiração e retry continuam exercitados;
sem `render`, o fluxo falha fechado. O helper é servido com `no-store`.

## Qualificação da fonte

Os testes de provider usam mocks e verificam contrato estrito, transporte com
falha, expiração e replay. O teste do endpoint usa somente credenciais e sessões
sintéticas. `scripts/test-turnstile-browser.mjs` exercita UI real em viewport
mobile com SDK/API simulados: rejeição, expiração e falha de carregamento,
preservação dos campos e token novo no retry. Execute com Playwright instalado
no ambiente de testes; `TURNSTILE_PLAYWRIGHT_PACKAGE` aceita seu caminho explícito.
No Animus, `ANIMUS_TEST_PYTHON` seleciona o Python de testes com Jinja2.

Esses resultados qualificam a fonte; após publicação coordenada, ainda é
necessário obter token real, executar o endpoint protegido e rejeitar seu replay.
Não considerar healthcheck, widget renderizado ou teste mock como aceite produtivo.

## Publicação e recuperação

Preserve imagem, configuração privada, volumes e estado anteriores em checkpoint
recuperável. Publique apenas os serviços afetados, conservando IDs/StartedAt dos
peers, a lease de capacidade e reserva da VPS. Rollback restaura imagem e ambiente
anteriores juntos; não altera usuários, senhas, dados ou sessões existentes.
Os recibos e backups privados seguem a política corporativa de recuperação.
Segredos e dados locais nunca entram no Git.

Fontes: [Siteverify](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/)
e [renderização](https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/).
