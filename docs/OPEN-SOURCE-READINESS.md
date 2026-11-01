# Revisão de preparação open source — 2026-11-01

Estado: **bloqueado para mudança de visibilidade**. Preparação do código e da
documentação não confirma segurança do ambiente nem publicação pública.

## Escopo e evidências

Checkout canônico `C:/repo/animus`, branch `master`, base
`6fe8977b606726511d372f00b2eb1de97a7e205d`. O arquivo local não versionado
`scripts/configure-local-peer.py` é preexistente e foi preservado fora da entrega.

A revisão inicial inspecionou 588 blobs alcançáveis pelas refs locais após
fetch. O Gitleaks 8.30.1 percorreu 118 commits e aproximadamente 1,63 MB;
seus dois alertas apontam uma fixture sintética de detecção em
`tests/test_obsidian.py`, não uma chave Stripe operacional demonstrada.
Scanners por padrão não detectaram o segredo HMAC específico abaixo.
Relatórios brutos ficam fora do repositório e não devem ser publicados.

## Bloqueio principal

`tests/test_vps_peer.py` continha um fallback HMAC literal e dados específicos
do ambiente: endereço interno do hub, IDs de workspaces, nomes de notas e
identificador de transcrição. Esta alteração retira esses valores da versão
atual e exige configuração explícita. O diagnóstico não integra a suíte
automática, pois pode coletar e sincronizar dados reais.

A issue privada #5 registra comparação anterior entre o fallback e o segredo
ativo do hub. Ela continua aberta. A PR #6 removeu o fallback de outra linha
de desenvolvimento e explicitou que não realizou rotação nem limpeza do
histórico. Nenhum segredo foi rotacionado nesta preparação.

Antes de abrir o repo, confirmar no ambiente proprietário que o segredo foi
rotacionado, o anterior é rejeitado e os peers autorizados foram migrados.
Coordenar a mudança para não desconectar clientes nem perder dados.

Mesmo após rotação, revisar os dados operacionais e pessoais remanescentes
no histórico, outras branches, tags, releases, anexos e discussões antes da
abertura. Eliminar histórico remoto ou excluir releases exige uma decisão
delimitada, backup e autorização específica; não está feito por este commit.
Resultados complementares são registrados separadamente após inspeção.

A comparação exata do segredo conhecido localizou um blob histórico em
`tests/test_vps_peer.py`. Também foram inspecionados os textos das 28 releases,
os quatro anexos disponíveis (wheel, dois ZIPs de recuperação e checksums) e
as dez issues/PRs com seus comentários de issues: nenhum continha esse valor
conhecido. Isso não equivale a revisão integral de toda informação sensível
nos anexos, comentários de revisão inline, logs de CI ou configurações do host.

## Licença e identidade

AGPL-3.0-only passa a reger o código a partir desta alteração, com copyright
original preservado e Guilherme Pinheiro / Datano identificados como origem.
Versões MIT anteriores continuam com as permissões já concedidas; o texto
anterior foi preservado em `docs/licenses/LEGACY-MIT.txt`. Não se reivindica
titularidade de contribuições ou marcas de terceiros. Forks e uso comercial
continuam permitidos nos termos da licença.

## Fechamento necessário

- Confirmar rotação do segredo com evidência do ambiente, sem publicar valores.
- Delimitar e autorizar saneamento de refs/histórico e eventuais anexos sensíveis.
- Revisar a procedência de contribuições e os artefatos que serão públicos.
- Repetir a varredura sobre o conjunto exato a publicar.
- Confirmar CI do SHA entregue e publicar a página institucional pelo fluxo do site.
- Só então mudar a visibilidade e confirmar acesso público sem autenticação.

## Plano delimitado para a decisão de saneamento

O plano proposto é preservar um bundle privado das refs antes de qualquer
reescrita; remover o segredo e os identificadores operacionais do diagnóstico
em todas as branches e tags que os contenham; revisar o diff de conteúdo e o
mapa de SHAs; e somente após autorização atualizar as refs remotas afetadas.
PRs e caches do provedor podem continuar mantendo objetos antigos e precisam
de tratamento próprio. Não excluir releases ou anexos sem evidência concreta.
Essa reescrita muda SHAs e exige reconciliar checkouts e atualizadores; portanto
o push normal desta preparação não executa nem autoriza esse procedimento.

## Validação local da preparação

42 testes passaram (autenticação administrativa, configuração e servidor);
cinco diagnósticos nativos ficaram intencionalmente fora da execução automática.
A execução direta sem configuração explícita foi verificada: encerra antes
de coletar ou acessar a rede. Metadados TOML e licença foram conferidos.
Isso não qualifica a instalação produtiva nem comprova rotação de credenciais.

## Execução autorizada — 2026-11-01

O usuário autorizou backup privado, reescrita, coordenação das credenciais,
abertura pública e publicação da página. Foram reescritos 123 commits e
atualizadas atomicamente 42 refs remotas, usando leases dos SHAs anteriores.
A verificação dos blobs alcançáveis não encontrou os valores removidos.
Backups completos e o mapa de commits ficam em área privada com acesso
restrito no Windows e na VPS; não são publicados com o projeto.

A conferência ao vivo demonstrou que o hub já havia migrado para três chaves
individuais: segredo compartilhado vazio, registro 0600, nonce obrigatório
e revogação explícita do segredo histórico. Todas as três chaves atuais
receberam HTTP 200; o segredo antigo, replay, ausência de autenticação e
identidade desconhecida receberam HTTP 401. Os consumidores Windows e VPS
também autenticaram com suas próprias configurações reais (HTTP 200).
Dois peers estavam online; uma credencial de peer offline permanece habilitada
sem usar o segredo revogado. Nenhuma nova chave ou dado de usuário foi alterado.

A fonte endurecida que já estava em produção foi integrada à master pública,
preservando a AGPL e os avisos de autoria. A atualização de fontes não instala
 automaticamente outra versão nos runtimes existentes. Referências históricas
a SHAs anteriores podem exigir o mapa privado para reconciliação. Caches e
refs internas do provedor não são controlados por um force-push: saneamento
de refs publicadas e revogação não são promessa de eliminação de toda cópia.
