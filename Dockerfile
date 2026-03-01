# =========================
# STAGE 1 — BUILDER
# =========================
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc libpq-dev curl ca-certificates libatomic1 \
    nodejs npm && \
    rm -rf /var/lib/apt/lists/*

RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV XDG_CACHE_HOME="/app/.cache"
ENV PRISMA_HOME="/app/.prisma"
ENV PRISMA_PY_BINARIES_PATH="/app/prisma_binaries"
# This tells the Node Prisma CLI where to cache its binary too
ENV PRISMA_BINARY_CACHE_DIR="/app/.cache"

RUN prisma generate

# Verify the binary landed in /app, not /root
RUN find /app/.cache -name "query-engine*" 2>/dev/null || echo "WARNING: binary not in /app/.cache"
RUN find /root/.cache -name "query-engine*" 2>/dev/null || echo "OK: nothing in /root/.cache"


# =========================
# STAGE 2 — RUNTIME
# =========================
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq5 supervisor nginx ca-certificates libatomic1 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /app /app

RUN addgroup --system appgroup && adduser --system --group appuser
RUN chown -R appuser:appgroup /app

USER appuser

ENV XDG_CACHE_HOME="/app/.cache"
ENV PRISMA_HOME="/app/.prisma"
ENV PRISMA_PY_BINARIES_PATH="/app/prisma_binaries"
ENV PRISMA_BINARY_CACHE_DIR="/app/.cache"

EXPOSE 8000 8001 8003 8004 8005 8006 8007

CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]