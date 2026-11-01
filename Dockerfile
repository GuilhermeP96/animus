ARG PYTHON_BASE=python:3.12.15-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
FROM ${PYTHON_BASE}

ARG SOURCE_REVISION
LABEL org.opencontainers.image.revision="${SOURCE_REVISION}" \
    org.opencontainers.image.version="0.8.15" \
    maintainer="datano" \
    description="Animus Hub — AI Memory Synchronization Server"

WORKDIR /app

# Preserve the verified current Debian major; require an exact codename match.
ARG BASE_CODENAME=trixie
RUN case "$BASE_CODENAME" in bookworm|trixie) ;; *) exit 1 ;; esac && \
    test "$(. /etc/os-release; echo "$VERSION_CODENAME")" = "$BASE_CODENAME"
# System deps
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Compatible patched build/installer tools; exact official wheel hashes.
COPY scripts/docker/toolchain-patch.requirements.txt /tmp/animus-toolchain.requirements.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes \
    -r /tmp/animus-toolchain.requirements.txt && python -m pip check \
    && rm /tmp/animus-toolchain.requirements.txt

# Python deps
COPY pyproject.toml ./
COPY . .
RUN pip install --no-cache-dir .
RUN mkdir -p /opt/animus-packages \
    && pip wheel --no-cache-dir --no-deps --wheel-dir /opt/animus-packages .

# Data volume
RUN install -d -m 0700 /data/animus
VOLUME /data/animus

# Environment
ENV ANIMUS_DATA_DIR=/data/animus \
    ANIMUS_PACKAGE_DIR=/opt/animus-packages \
    ANIMUS_NODE_ROLE=hub \
    ANIMUS_SERVER_HOST=0.0.0.0 \
    ANIMUS_SERVER_PORT=8314

EXPOSE 8314

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -fsS --max-time 3 http://localhost:8314/health/live || exit 1

CMD ["uvicorn", "animus.server.app:app", "--host", "0.0.0.0", "--port", "8314"]
