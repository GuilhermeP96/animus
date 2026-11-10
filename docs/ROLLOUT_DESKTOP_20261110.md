# Animus Desktop 0.9.0 / 0.9.1 — entrega de 10/11/2026

Entregue o aplicativo Windows compilado, daemon sem console via `pythonw.exe`,
bandeja animada e painel local. A 0.9.1 corrige o ícone pouco legível da 0.9.0:
dez resoluções nativas de 16 a 256 px, PNG/RGBA de 32 bits, traços ópticos para
tamanhos pequenos e renderização da bandeja no tamanho efetivo do Windows.
A janela/barra de tarefas recebe o ícone completo, com identidade estável.
Não foi necessário reiniciar o Explorer nem alterar preferências do Windows.

Prioridade: desconexão → MCP → sincronização → conectado → ocioso. A indicação
MCP é magenta; concorrência com sincronização acrescenta arco ciano. Um alerta
de desconexão continua vermelho com ponto magenta para atividade MCP local.
Contadores por instância, chamadas aninhadas, heartbeat e conclusão por quatro
segundos evitam uma chamada apagar outra ou produzir piscadas curtas.

## Artefatos imutáveis

[Release 0.9.1](https://github.com/GuilhermeP96/animus/releases/tag/v0.9.1), fonte
`3adef419caf753e709dd3af18680b426a0c76ba4`. A 0.9.0 e seus assets foram preservados.

| Artefato | SHA-256 |
| --- | --- |
| Animus.exe | `e26fd1243ee7613452d7ab45b0af5cda1275b80993e3ac73ccfd78ee43047d35` |
| ZIP Windows | `dfbf7b8c0fa2978de65fedb2fcb2bbc4bdf5bf5677d954c0c29add016e7045e1` |
| Wheel 0.9.1 | `3485a6615c4f423d2c0b70534408b837b660bbb1a45c0ca44f64dc0fbe86e867` |

Readback dos cinco assets GitHub conferido antes da publicação estável.
Não há assinatura Authenticode/destacada alegada. A origem usa HTTPS e o
download do wheel pelos peers usa HMAC; SHA-256 verifica integridade.

## Validação observada

- Suíte Linux: 454 testes e 15 subtestes aprovados; cinco skips de plataforma.
- QA independente dos bytes finais: dez recursos PE com alpha real; 1.500
  quadros em 2,763 s, handles GDI/User estáveis. Ícone de 16 px com 54 pixels
  de alpha ≥ 200; de 24 px com 105. Preview em tamanho nativo inspecionado.
- MCP: concorrência em processos/threads, deduplicação, prioridades, expiração,
  exceções e preservação da instância restante comprovadas em fixtures.
- Wheel: 39 arquivos Python correspondem à fonte; licenças e RECORD válidos.
- Produção: hub saudável e peers nativos Windows/Linux instalados em 0.9.1;
  ambos passaram em HTTP HMAC, `pip check` e 59 arquivos iguais ao wheel.
  As duas tarefas Windows estão ativas e o processo do app usa o novo diretório
  de versão. Atalhos de Desktop/Menu Iniciar foram atualizados.
- Novas conexões pelos comandos MCP configurados: 16 ferramentas e estatísticas
  frescas nos dois hosts. Handshake legado 0.1.0 permanece separado da versão
  instalada 0.9.1, verificada por metadados/arquivos.
- Configurações dos peers/hub e registry de chaves idênticos em bytes; zero
  memórias ausentes ou conteúdos alterados na comparação com backups consistentes.
  A sincronização normal renovou timestamps/ordem de tags de 21 notas, sem mudar
  conteúdo, metadados de origem ou conjunto de tags. Não se declara a base ativa
  idêntica em bytes durante a coleta normal.
- Datano, Academy e serviço fiscal mantiveram containers/imagens e saúde.

Nenhuma configuração, endereço de implantação, credencial, memória ou log bruto
foi incluído nos novos artefatos. O build usa somente fonte versionada; a revisão
dos arquivos descompactados não encontrou os valores privados conhecidos.
Recibos, logs, dumps e checkpoints ficam privados nos respectivos hosts.

## Limites e operação

As jornadas GUI isoladas de sincronização, singleton e fechamento para bandeja
passaram. A conferência visual automática final da barra de tarefas em produção
foi interrompida pelo controle Escape; não é registrada como concluída. A
instalação, recursos do executável, processo ativo e checks de backend foram
conferidos separadamente. Não houve qualificação de máquina limpa ou reboot.
GitHub Actions permanece desativado; o check de grafo de dependências não é CI
de testes aprovado.

O indicador depende de um MCP com o código novo carregado. Sessões iniciadas
antes da instalação precisam reconectar; nenhum cliente/chat foi encerrado.
O Linux permanece headless, sem tray nem nova porta. Backups de SQLite, configs,
tarefas, registry, wheels e imagens anteriores são mantidos para recuperação;
não se restauram credenciais revogadas nem se removem trabalhos preexistentes.
