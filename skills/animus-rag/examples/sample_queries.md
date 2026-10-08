# Animus RAG Query Examples

### Contextual Recall (RAG)
```bash
# General query with workspace focus
.agents/skills/animus-rag/scripts/rag_recall.py -c "configuracao do nginx proxy e ssl para zabbix" -w "vps-hub"

# Recall with increased token limit for complex tasks
.agents/skills/animus-rag/scripts/rag_recall.py -c "celery worker redis setup for aura" -t 4000 --detailed
```

### Full-Text Search (Eagle Vision)
```bash
# Search for error messages or docker commands
.agents/skills/animus-rag/scripts/search.py "docker-compose up postgres" -n 5

# Search specifically within Claude Code or Antigravity sessions
.agents/skills/animus-rag/scripts/search.py "wireguard port mapping" -t claude_chat
```

### Session Inspection
```bash
# List recent sessions
.agents/skills/animus-rag/scripts/session.py --list -n 10

# Read full session transcript
.agents/skills/animus-rag/scripts/session.py -s "ddf882aa-426e-45d3-8e26-86bebd3dcad1" --limit 50
```

### Store Memory
```bash
# Store important operational decision
.agents/skills/animus-rag/scripts/remember.py -t "Portas e proxy do Zabbix no VPS Hub" \
  -c "O frontend Zabbix roda em zbx.gp96.com.br porta 8080 interna, exposto via nginx proxy com SSL." \
  -w "vps-hub" --tags "zabbix,nginx,docker,ssl"
```
