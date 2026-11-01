# Segurança e privacidade

Não publique credenciais, transcrições ou detalhes exploráveis em issues.
Use o canal privado do mantenedor em https://datano.com.br/contato para
combinar o recebimento seguro do relato; não envie segredos no formulário.

O código open source não dá acesso ao hub privado da Datano, a contas nem
às memórias de qualquer usuário. Configure seu próprio hub, HTTPS e segredos
fortes e distintos. Preserve autenticação e backups. Não use versões antigas
sem avaliar as correções de segurança posteriores.

Conversas, configurações e notas podem conter informações pessoais ou
corporativas mesmo quando um filtro automático não encontra credenciais.
Selecione somente fontes autorizadas e revise o conteúdo antes de coletar,
sincronizar, exportar ou publicar. Não há garantia de anonimização automática.

Um segredo removido de um arquivo permanece no histórico, branches, tags,
releases e cópias existentes. Exposição exige rotação coordenada, invalidação
da credencial anterior e verificação dos consumidores. A remoção de arquivos
ou a aprovação de um scanner não substitui essa rotação.

O diagnóstico `tests/test_vps_peer.py` lê históricos reais e pode sincronizar
dados. Ele é excluído da execução automática dos testes. A execução direta
exige diretório, hub, segredo e autorização explícita via variáveis de ambiente.
