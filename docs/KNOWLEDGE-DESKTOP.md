# Conhecimento Obsidian na GUI

O painel Conhecimento é uma interface para o **vault já configurado** e o mesmo
`animus.db` do peer. As notas continuam sendo Markdown canônico. Salvar pela GUI
edita o arquivo original e atualiza a identidade estável no índice; não cria
outro vault, outro banco ou uma cópia editável paralela.

## Jornada

1. Abra **Conhecimento Obsidian** na bandeja ou no painel principal.
2. Escolha o vault, busque por texto/projeto e filtre por status. A navegação
   acompanha as pastas do vault em uma árvore que pode ser expandida ou recolhida.
3. Selecione uma nota para ler ou editar Markdown, título, projeto, status e
   sensibilidade. A aba Leitura renderiza Markdown/GFM com tabelas, listas de
   tarefas, notas de rodapé, callouts, código destacado e fórmulas matemáticas.
   Mermaid é renderizado localmente; HTML ativo e scripts da nota não são executados.
   A aba **Leitura** é a visão inicial. A aba **Grafo do vault** projeta os
   wikilinks das notas retornadas pela busca; para manter a interface responsiva,
   a visualização mostra até 120 nós e orienta a refinar a busca quando necessário.
4. Salve no vault. O Animus registra backup e auditoria, indexa a mesma nota e
   solicita o ciclo normal do daemon.
5. A interface distingue arquivo ainda não indexado, edição pendente de envio e
   nota recebida pelo hub. O botão Sincronizar usa o canal autenticado existente.

Atalhos: Ctrl+F para buscar, Ctrl+S para salvar, Ctrl+N para nova nota e F5 para
atualizar a lista. Em telas menores o painel oferece rolagem, preservando o acesso
aos controles. Texto ainda não salvo permanece no editor durante consultas e só
é descartado após confirmação.

Os botões **Expandir tudo** e **Recolher** controlam somente a apresentação da
árvore. A hierarquia, o grafo e seus filtros não movem, renomeiam ou reescrevem
arquivos. A navegação carrega até 2.000 notas por consulta; vaults maiores
continuam pesquisáveis por texto, projeto e status.

Diagramas Mermaid e imagens têm controles de zoom, pan por arraste, ajuste à
tela, tamanho original e visualização ampliada. Ctrl + roda aplica zoom no
objeto; setas movem, mais/menos ampliam/reduzem e Home restaura o enquadramento.
A leitura pode abrir em uma janela ampla. Diagramas podem ser exportados em SVG;
tabelas oferecem rolagem, ampliação e cópia como CSV, e blocos de código têm
cópia e quebra de linhas. Esses controles alteram a visualização, não a nota.

Desde o Desktop 0.9.5.1, a janela Conhecimento pode ser redimensionada e
maximizada: a lista e a área de edição/leitura crescem com o espaço disponível.
Em telas menores, a rolagem mantém os controles acessíveis. A barra de título
nativa acompanha as cores da janela, respeitando o alto contraste do Windows.
Os controles da área de conhecimento usam a mesma paleta escura, inclusive
árvore, listas suspensas, botões e abas, com estados de foco e desabilitado
legíveis. A árvore hierárquica, o grafo e a leitura inicial integram o Desktop
0.9.5.2.

O botão **Abrir só leitura** (Ctrl+Shift+R) e **Tela ampla** na prévia abrem uma
janela independente, redimensionável e sem controles de edição. Ela permanece
aberta ao fechar ou minimizar Conhecimento. Wikilinks, imagens e os controles
dos diagramas continuam funcionando nessa janela. Uma prévia de texto ainda
não salvo é identificada como rascunho; abrir a leitura não salva nem descarta
o editor. Fechar a bandeja encerra também essas janelas.

Wikilinks navegam pelas fontes canônicas; referências ambíguas são rejeitadas.
Imagens locais são resolvidas somente dentro do vault, com limites de formato
e tamanho. Imagens e outros recursos externos não são carregados automaticamente.

Novas notas são criadas em `Conhecimento` dentro do vault escolhido. Mudanças de
projeto registram classificação manual para respeitar a curadoria humana. Notas
na área `.animus/exported/Conhecimento` também são coletadas e sincronizadas:
a exclusão interna genérica `.animus/**` preserva backups, quarentena e artefatos,
enquanto regras explícitas mais específicas continuam sendo respeitadas.

## Preservação e governança

- Uma revisão SHA-256 do arquivo é exigida ao salvar. Se outra janela ou editor
  tiver alterado a fonte, o salvamento é rejeitado e o texto em edição é mantido.
  Escritores da GUI são serializados por trava de arquivo. No Windows, o
  salvamento mantém um handle que bloqueia outras escritas e substituições,
  confere a revisão e grava um backup com flush antes de alterar a fonte.
  Uma interrupção de energia durante a gravação pode exigir recuperar esse
  backup; a interface não promete uma transação entre arquivo e índice.
- UTF-8, BOM e CRLF/LF da nota existente são preservados. Metadados não editados,
  comentários e blocos YAML permanecem como estavam. Campos escalares complexos
  que não possam ser alterados com segurança exigem revisão na origem.
- Alterações geram backup e auditoria no namespace gerenciado do vault. Esses
  arquivos não são tratados como notas ativas. Notas depreciadas preservam o
  histórico em vez de serem apagadas.
- O status verificado exige confirmação humana explícita. Alterar o conteúdo de
  uma nota verificada exige nova confirmação ou mudança de status. A GUI não
  aprova exemplos de treino; notas já aprovadas para treino exigem revisão dessa
  aprovação na origem antes de serem editadas.
- Links/reparse points, travessia de diretórios, namespaces internos e padrões
  reconhecidos de segredo são rejeitados nas operações de escrita.
- Sem coleta Obsidian habilitada, a interface permanece somente leitura.
  Uma falha de indexação mantém o arquivo canônico salvo e indica a pendência;
  o coletor normal pode retomar a indexação sem duplicar a nota.

O índice e o protocolo preservam o Markdown completo das notas Obsidian, incluindo
YAML, código, Mermaid e tabelas. A busca FTS trabalha sobre esse conteúdo sem
substituí-lo por uma versão simplificada. Notas antigas são reindexadas a partir
dos arquivos canônicos; o sistema não inventa formatação ausente da fonte.

O hub sincroniza o conteúdo indexado entre peers. Não transforma cada peer em
um espelho editável de todos os arquivos de todos os vaults. A GUI trabalha com
as fontes canônicas configuradas no peer Windows; o peer Debian consulta e sincroniza pelo
Animus sem instalar uma interface gráfica.

## Integração

A GUI inicia `pythonw -m animus.desktop_knowledge` com JSON por stdin/stdout,
sem console ou porta HTTP local. Há uma lista fechada de operações; nenhum
comando de shell, endpoint, token ou configuração é fornecido pelo documento.
O processo usa o diretório de dados já selecionado pelo aplicativo. Os limites
de leitura, paginação e erros são explícitos; notas e credenciais não entram em
logs de erro ou no executável distribuído.

A leitura avançada usa o Microsoft Edge WebView2 Runtime instalado, com perfil
isolado e mapeamento somente dos assets locais. Não há servidor HTTP local nem
objeto nativo exposto ao documento. CSP, sanitização e bloqueio de recursos e
navegação limitam a prévia; o canal do renderizador oferece operações de leitura
e ações explícitas de navegação/cópia/exportação, sem salvar notas por JavaScript.
As bibliotecas estão empacotadas offline e fixadas por hash, com suas licenças.
Veja [notas de terceiros](../desktop/windows/THIRD-PARTY-NOTICES.md).
