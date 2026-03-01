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

# Must be set BEFORE prisma generate so the binary lands in /app, not /root/.cache
ENV XDG_CACHE_HOME="/app/.cache"
ENV PRISMA_HOME="/app/.prisma"
ENV PRISMA_PY_BINARIES_PATH="/app/prisma_binaries"

RUN prisma generate


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

# /app/.cache and /app/.prisma are subdirectories of /app, so this covers them
RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000 8001 8003 8004 8005 8006 8007

CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]