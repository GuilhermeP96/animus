# Animus Desktop 0.9.5.2

O painel **Conhecimento Obsidian** oferece busca, leitura e edição Markdown,
classificação por projeto e curadoria de status no vault canônico do peer.
Salvamentos usam a mesma identidade de nota, banco e fila de sincronização do
Animus, com conflito de edição, backup e auditoria. Não é criado outro vault.
Mermaid, tabelas, código, fórmulas e objetos têm renderização local, zoom, pan e
área ampliada. Requer o Microsoft Edge WebView2 Runtime; SDK, renderizadores e
fontes acompanham o pacote, com hashes e licenças.
O Debian continua executando somente o peer/MCP em segundo plano.
Consulte [Conhecimento na GUI](../docs/KNOWLEDGE-DESKTOP.md).

Os créditos incluem a marca vetorial oficial da Datano, incorporada ao app,
com links diretos para a página do Animus e seu repositório GitHub. Não há
download de imagens em tempo de execução. `-DesktopOnly` no instalador permite
atualizar só a interface de um peer existente, preservando sua tarefa de daemon.

O ícone do aplicativo contém dez resoluções nativas de 16 a 256 px, com alpha
32 bits e espessuras ajustadas para tamanhos pequenos. A bandeja renderiza na
resolução efetiva do Windows/DPI, sem reduzir um traço fino de 64 px para 16 px.

Aplicativo Windows compilado, sem console, com painel local e ícone triangular
animado na bandeja. Clique no ícone para abrir; fechar a janela recolhe o painel.
Sair da bandeja encerra somente a interface. O peer continua em segundo plano.

| Cor | Estado observado |
| --- | --- |
| Verde | Conexão autenticada recente confirmada pelo daemon |
| Ciano | Coleta ou sincronização em andamento |
| Violeta | Ocioso, aguardando o próximo ciclo após conexão confirmada |
| Magenta | Em uso pelo MCP, com chamadas/processos simultâneos contabilizados |
| Vermelho | Sem conexão confirmada, daemon parado ou heartbeat expirado |

Prioridade de indicação: desconexão → MCP → sincronização → conectado → ocioso.
Quando MCP e sincronização concorrem, o triângulo fica magenta e recebe um arco
ciano; o texto mantém as duas atividades visíveis. Uma desconexão permanece
vermelha, com a contagem MCP local em segundo plano. Chamadas curtas deixam
um sinal de conclusão por quatro segundos para evitar piscadas. Cada instância
MCP escreve seu próprio contador; terminar uma chamada não apaga outra ativa.
Heartbeats vencidos e processos encerrados são desconsiderados. O indicador
depende da versão nova do servidor MCP: sessões já abertas devem reconectar.

O painel mostra contagens locais, fila, workspaces, versão, última conexão,
último ciclo e eventos seguros. `Sincronizar agora` solicita o próximo ciclo
normal, respeitando as opções de coleta já configuradas. Fila vazia, sozinha,
não significa que há conexão. Contagens indisponíveis aparecem como `—`.

## Instalação no peer existente

Requer Windows 10/11 com .NET Framework 4.8 e o runtime privado do peer já
configurado em `%USERPROFILE%\.animus\runtime`. `Animus.exe` é a interface
compilada; coleta, MCP e atualização continuam no runtime Python do Animus.
O daemon utiliza `pythonw.exe`, sem janela de terminal. A instalação não muda
credenciais, opções de coleta, banco, notas nem processos MCP de chats abertos.

Baixe o ZIP e SHA256SUMS da release oficial. Extraia numa pasta e confira o
hash do executável antes de executar o instalador com a conta dona do peer:

```powershell
.\install-desktop.ps1 -PackageDirectory . -ExpectedSha256 HASH_PUBLICADO_DO_ANIMUS_EXE -ExpectedManifestSha256 HASH_PUBLICADO_DO_MANIFESTO
```

Confira o ZIP contra o SHA256SUMS externo da release e obtenha os hashes do EXE
e do manifesto interno nas notas oficiais. O instalador verifica ambos antes
de confiar na lista de assets.

O instalador preserva os triggers/settings/principal da tarefa `AnimusPeerDaemon`
e troca somente seu interpretador por `pythonw.exe`. Registra `AnimusPeerTray`
no logon interativo, cria atalhos no Desktop/Menu Iniciar e usa um diretório
imutável por versão sob `.animus/desktop`. Guarda os arquivos privados no host.
Feche o ícone pelo menu antes de trocar o executável. Reinstalação aceita somente
os mesmos bytes da versão instalada. A atualização do wheel do daemon permanece
pelo canal HTTPS/HMAC existente; o binário desktop tem seu próprio SHA-256.
Não é alegada assinatura Authenticode nem instalação autônoma sem runtime.

No Linux/headless, o daemon usa o mesmo status seguro e continua em systemd.
Não é criado tray num servidor sem sessão gráfica.

## Compilar e verificar

Execute `scripts/build-desktop.ps1` no Windows. O compilador .NET do sistema gera
`dist/desktop/Animus.exe` como subsistema Windows GUI e incorpora o triângulo
como ícone. O código C# é UTF-8, o compilador usa `/codepage:65001` e os scripts
PowerShell são ASCII para compatibilidade com 5.1/7. O JSON local é UTF-8 sem BOM.
Nenhum arquivo de configuração, endereço de infraestrutura, memória ou segredo
é usado como entrada do build. A distribuição contém EXE, SDK WebView2,
bibliotecas locais de renderização, licenças, NOTICE, instalador, documentação
e checksums. A leitura avançada requer o Microsoft Edge WebView2 Runtime.

O IPC usa `peer-status.json`, `peer-command.json` e `mcp-activity/` somente na pasta privada de
dados. Há limite de tamanho, heartbeat, expiração de comando e escrita por
substituição. Nenhuma porta local ou endpoint público adicional é aberto.
O status não contém URL do hub, chaves, caminhos de memórias ou conteúdo.
Ao compartilhar diagnóstico, revise dados locais e nunca publique a pasta
`.animus`, configs, backups ou logs brutos.
