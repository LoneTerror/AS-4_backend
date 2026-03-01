# =========================
# STAGE 1 — BUILDER
# =========================
FROM python:3.11-slim AS builder

WORKDIR /app

# Build deps + Node (only for prisma generate)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Virtualenv
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# ---- Prisma paths ----
ENV HOME=/app \
    PRISMA_PY_BINARIES_PATH=/app/prisma_binaries \
    PRISMA_HOME=/app/.prisma \
    XDG_CACHE_HOME=/app/.cache

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Generate Prisma client + engine
RUN mkdir -p /app/prisma_binaries /app/.prisma /app/.cache
COPY prisma/schema.prisma ./prisma/
RUN prisma db pull
RUN prisma generate


# =========================
# STAGE 2 — RUNTIME
# =========================
FROM python:3.11-slim

# Create non-root user
RUN addgroup --system appgroup && adduser --system --group appuser

WORKDIR /app

# Runtime deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl supervisor nginx ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# ---- Prisma + Runtime paths ----
ENV HOME=/app \
    PRISMA_PY_BINARIES_PATH=/app/prisma_binaries \
    PRISMA_HOME=/app/.prisma \
    XDG_CACHE_HOME=/app/.cache \
    PYTHONPATH=/app \
    VIRTUAL_ENV=/app/venv \
    PATH="/app/venv/bin:$PATH"

# Copy built assets
COPY --from=builder /app/venv /app/venv
COPY --from=builder /app/prisma_binaries /app/prisma_binaries
COPY --from=builder /app/prisma /app/prisma
COPY --from=builder /app/.prisma /app/.prisma
COPY --from=builder /app/.cache /app/.cache

# Copy app source
COPY . .

# Supervisor + Nginx config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
RUN rm -rf /etc/nginx/nginx.conf /etc/nginx/sites-enabled/*
COPY nginx.conf /etc/nginx/nginx.conf

# Create runtime dirs + FIX PERMISSIONS (important for prisma)
RUN mkdir -p \
    /var/log/nginx \
    /var/lib/nginx \
    /run/nginx \
    /var/log/supervisor \
    /tmp/client_temp \
    /app/.cache \
    /app/.prisma && \
    chown -R appuser:appgroup \
    /app \
    /var/log \
    /var/lib/nginx \
    /run/nginx \
    /etc/nginx \
    /tmp

# Switch to non-root
USER appuser

EXPOSE 8000 8001 8003 8004 8005 8006 8007

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]