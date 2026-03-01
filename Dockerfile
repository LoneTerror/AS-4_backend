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

# Set cache dirs to /app-owned paths BEFORE generating
ENV XDG_CACHE_HOME="/app/.cache"
ENV PRISMA_HOME="/app/.prisma"
ENV PRISMA_PY_BINARIES_PATH="/app/prisma_binaries"

RUN prisma generate

# Make sure appuser will be able to read the binaries
RUN chmod -R 755 /app/.cache /app/.prisma || true


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

# chown must happen BEFORE switching user, and must cover the cache dirs
RUN chown -R appuser:appgroup /app

USER appuser

# These must match what was used during prisma generate
ENV XDG_CACHE_HOME="/app/.cache"
ENV PRISMA_HOME="/app/.prisma"
ENV PRISMA_PY_BINARIES_PATH="/app/prisma_binaries"

EXPOSE 8000 8001 8003 8004 8005 8006 8007

CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]
