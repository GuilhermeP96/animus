# Skill Animus RAG e configuração segura

Issue: https://github.com/GuilhermeP96/animus/issues/3
Incidente: https://github.com/GuilhermeP96/vps-hub/issues/8

Fonte canônica: `skills/animus-rag/` neste repo. Instalar/restaurar com
`bash scripts/install-rag-skill.sh`; destino padrão `/root/.agents/skills/animus-rag`.
O instalador arquiva a skill anterior em área 0700 e compara todos os arquivos
instalados com a fonte. Para rollback, extrair o arquivo privado anterior no
destino e validar novamente. Preservar regras independentes fora desta skill.

Os helpers usam `/opt/animus-peer/bin/python3` com as dependências do peer.
Eles carregam configuração persistida e variáveis ANIMUS, mas não leem `.env`
do diretório de um projeto chamador. Erros de validação ocultam valores de
entrada. Não imprimir exceções antigas, credenciais ou conteúdo sensível de
memórias em logs públicos. Nenhuma configuração de daemon ou credencial muda.

Validar com `python -m unittest discover -s tests -p test_helper_config.py`
no ambiente do peer, e consulta à skill instalada a partir do cwd do Hub.
O caso canário confirma exclusão de dotenv e ocultação de valores em erros.
Esta mudança não soluciona a revisão/rotação de credenciais do incidente.
