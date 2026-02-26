# ---------- STAGE 1: BUILDER ----------
FROM python:3.11-slim AS builder
WORKDIR /app

# (Keep your apt-get and venv setup the same)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Set the binary path
ENV PRISMA_PY_BINARIES_PATH=/app/prisma_binaries

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# NEW: Explicitly create the directory before generating
RUN mkdir -p /app/prisma_binaries

COPY prisma/schema.prisma ./prisma/
# Generate and verify binaries are there
RUN prisma generate && ls -l /app/prisma_binaries

# ---------- STAGE 2: RUNTIME ----------
FROM python:3.11-slim

RUN addgroup --system appgroup && adduser --system --group appuser

# FIX: Tell the runtime app exactly where the binaries were moved
ENV PRISMA_PY_BINARIES_PATH=/app/prisma_binaries \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/venv \
    PATH="/app/venv/bin:$PATH" \
    HOME="/app"

WORKDIR /app

# Install runtime deps, Supervisor, AND Nginx
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl supervisor nginx && rm -rf /var/lib/apt/lists/*

# Copy the venv, prisma schema, and the engines from the builder stage
COPY --from=builder /app/prisma_binaries /app/prisma_binaries
COPY --from=builder /app/venv /app/venv
COPY --from=builder /app/prisma /app/prisma

# Copy source and configs
COPY . .
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Nginx configuration setup
RUN rm -f /etc/nginx/nginx.conf /etc/nginx/sites-enabled/default
COPY nginx.conf /etc/nginx/nginx.conf

# PERMISSIONS: Fix permissions for Nginx temp folders and Prisma binaries
RUN mkdir -p /var/log/nginx /var/lib/nginx /run/nginx /tmp/client_temp /var/log/supervisor && \
    chown -R appuser:appgroup /app /var/log /var/lib/nginx /run/nginx /etc/nginx /tmp && \
    chmod -R +x /app/prisma_binaries

USER appuser

# Expose Nginx port (8000) and Microservice ports
EXPOSE 8000 8001 8003 8004 8005 8006 8007

# Healthcheck now hits the Nginx proxy
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]