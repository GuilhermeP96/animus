# Recuperação local do Animus — credencial por identidade

Este ZIP contém somente fonte. Não contém Python, instaladores, segredos, tokens,
identidades privadas ou uma validade que expire antes de você abrir o pacote.
A validade começa na preparação local (padrão 1 hora; 60–3600 segundos).

## Antes de executar

Confirme o SHA256 do ZIP entregue pelo administrador no chat autenticado, antes
de extrair/executar. Use o Python já instalado pelo Animus nativo (>=3.10,
Animus e cryptography já disponíveis). Não reinstale clientes ou bibliotecas.
Abra PowerShell com a conta do proprietário; permissões administrativas podem
ser necessárias para parar/iniciar sua tarefa e definir ACL.

O lançador enumera tarefas, serviços e processos sem imprimir argumentos,
segredos ou valores de provedores. Suporta nesta versão somente uma tarefa
agendada com ação direta python.exe/pythonw.exe e módulo Animus. Wrappers,
serviços, ações múltiplas, identidade/processo ambíguos e principal sem acesso
à ACL são recusados: exigem qualificação do administrador, sem reinício guessed.
O estado Ready da tarefa não comprova que o peer esteja ativo.

## 1. Preparar (nenhuma mudança ativa)

```powershell
.\Recover-Animus.ps1 -Mode Prepare
# Se a descoberta não identificar a configuração certa:
.\Recover-Animus.ps1 -Mode Prepare -TaskName 'AnimusPeer' -TaskPath '\' -ConfigPath 'C:\Users\SEU_USUARIO\.animus\config.json'
```

Selecione e confirme a tarefa e o arquivo EXISTENTE que ela realmente utiliza.
A descoberta considera ANIMUS_DATA_DIR do ambiente/.env de WorkingDirectory
sem revelar outras variáveis. Se houver outra conta/env/argumento configurando
DataDir, forneça o caminho exato; não presuma o perfil padrão. A confirmação
explicita do proprietário é necessária mesmo com um só candidato.

Guarde o caminho privado exibido. Cole **somente** o JSON público final no chat
administrativo atual: node_id, public_key, fingerprint, rotation_id, expires_at.
A chave X25519 privada permanece local com ACL somente proprietário/SYSTEM/
Administradores. Nenhum provisionamento usa a credencial antiga ou rede.

O administrador verifica esse canal e a identidade esperada, gera uma credencial
nova por nó, registra-a no registry do servidor e devolve o envelope criptografado
mais seu SHA256 CANÔNICO no mesmo canal independente. O SHA não é o hash do
arquivo com espaços: é envelope_digest do JSON canônico do helper qualificado.
Se vencer o prazo, prepare um diretório/JSON novos; não amplie envelopes antigos.

## 2. Aplicar envelope aprovado

```powershell
.\Recover-Animus.ps1 -Mode Apply -RecoveryDir 'C:\Users\SEU_USUARIO\.animus-recovery-IDENTIFICADOR' -EnvelopePath 'C:\CAMINHO\envelope.json' -ExpectedDigest 'SHA256_CANONICO_RECEBIDO_NO_CHAT'
```

Confira o alvo e digite APPLY. O kit valida digest independente, nó, rotação,
destinatário, validade e AES-GCM, valida o modelo NATIVO instalado e prepara
backup privado + replacement com ACL antes de parar a tarefa exata.
Ele recusa ambiente ANIMUS_SECURE_AUTH diferente de 1 quando observado e exige
nonce no cliente nativo. Não acrescenta secure_auth ao JSON: modelos antigos
rejeitam campos desconhecidos e podem registrar o conteúdo no erro.
Somente server_secret muda; node_id/data_dir/provedores/filas/licença permanecem.
Config drift impede substituição. Depois de parada comprovada da tarefa/processo,
a troca é atômica (os.replace) e somente essa tarefa é reiniciada.

O pedido de início não comprova reconexão. Confirme o processo local e peça ao
administrador a aceitação real da mesma identidade no servidor/Hub. Qualquer
falha deixa uma pendência técnica owner=agent; não é um teste Windows concluído.

## Falhas, recuperação e retenção

Jamais restaure o server_secret antigo revogado. O backup existe para recuperar
outros campos: qualquer restauração manual deve manter a credencial nova. Se
houver falha após substituição, conserve a configuração nova e reconcilie a
pendência de runtime; não há fallback automático para a chave antiga.
O diretório privado contém chave, backup e recibos: não cole nem envie seus
arquivos em chat/Git/e-mail. Faça backup corporativo criptografado com upload,
listagem, tamanho, download e SHA verificados antes de remover cópia local,
seguindo scripts/backup-sharepoint-verify.py do VPS-Hub. Não delete por idade.
Os recibos não contêm segredo. Não execute o kit por tarefa diária/autônoma.

## Qualificação e limites

Testes na VPS validam criptografia real, expiração, adulteração, identidade,
travessia/symlink, preservação de campos e o modelo nativo instalado. ACL e
ScheduledTask precisam de execução assistida no Windows real pelo proprietário;
fixtures Linux não comprovam ACL, parada do processo ou reconexão de peer.
Serviços/wrappers não são suportados até revisão específica. O código não faz
requisições de rede nem usa licença/credencial antiga como canal de confiança.

## Transporte SSH administrativo autenticado (opcional)

Somente após autorização explícita do proprietário e verificação independente
nome do host/chave SSH, o administrador pode executar sem prompts usando
`-NonInteractive`. Esse parâmetro não estabelece confiança no transporte:
quem o utiliza deve comprovar SSH autenticado e identidade do equipamento.
Obrigatórios **nos dois modos**: TaskName, TaskPath, ConfigPath local absoluto e
ExpectedNodeId identificado independentemente. Não há descoberta/seleção
implícita nesse modo. O esperado é comparado ao inspect, enrollment, metadata
privada e config atual; qualquer mismatch bloqueia antes de stage/stop.
Apply ainda exige envelope e digest independentes e alvo idêntico ao Prepare.

```powershell
.\Recover-Animus.ps1 -Mode Prepare -NonInteractive -TaskName 'AnimusPeerDaemon' -TaskPath '\' -ConfigPath 'C:\Users\USUARIO\.animus\config.json' -ExpectedNodeId 'IDENTIDADE_CONFIRMADA' -RecoveryDir 'C:\Users\USUARIO\.animus-recovery-NOVO'
.\Recover-Animus.ps1 -Mode Apply -NonInteractive -TaskName 'AnimusPeerDaemon' -TaskPath '\' -ConfigPath 'C:\Users\USUARIO\.animus\config.json' -ExpectedNodeId 'IDENTIDADE_CONFIRMADA' -RecoveryDir 'C:\Users\USUARIO\.animus-recovery-NOVO' -EnvelopePath 'C:\ENVELOPE\envelope.json' -ExpectedDigest 'SHA256_CANONICO_INDEPENDENTE'
```

O padrão continua interativo com CONFIRM/APPLY. Pacotes antigos sem node_id
vinculado em runtime.json precisam de Prepare novo; não reutilize enrollment
antigo nesse modo. Tarefa Ready sem processo não comprova peer online.
