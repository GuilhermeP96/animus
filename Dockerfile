FROM python:3.12-slim

LABEL maintainer="datano" \
    description="Animus Hub — AI Memory Synchronization Server"

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir . 2>/dev/null || true
COPY . .
RUN pip install --no-cache-dir .

# Data volume
RUN mkdir -p /data/animus
VOLUME /data/animus

# Environment
ENV ANIMUS_DATA_DIR=/data/animus \
    ANIMUS_NODE_ROLE=hub \
    ANIMUS_SERVER_HOST=0.0.0.0 \
    ANIMUS_SERVER_PORT=8314

EXPOSE 8314

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -f http://localhost:8314/health || exit 1

CMD ["uvicorn", "animus.server.app:app", "--host", "0.0.0.0", "--port", "8314"]
