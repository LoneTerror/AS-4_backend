# ---------- STAGE 1: BUILDER ----------
FROM python:3.11-slim AS builder
WORKDIR /app

# Required for Prisma and Python dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# FIX: Force Prisma to download binaries to a path accessible in Stage 2
ENV PRISMA_PY_BINARIES_PATH=/app/prisma_binaries

RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY prisma/schema.prisma ./prisma/
# This generates the client and puts the binary engines in /app/prisma_binaries
RUN prisma generate

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
COPY --from=builder /app/venv /app/venv
COPY --from=builder /app/prisma /app/prisma
COPY --from=builder /app/prisma_binaries /app/prisma_binaries

# Copy source and configs
COPY . .
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Nginx configuration setup
RUN rm -f /etc/nginx/nginx.conf /etc/nginx/sites-enabled/default
COPY nginx.conf /etc/nginx/nginx.conf

# PERMISSIONS: Fix permissions for Nginx temp folders and Prisma binaries
RUN mkdir -p /var/log/nginx /var/lib/nginx /run/nginx /tmp/client_temp /var/log/supervisor && \
    chown -R appuser:appgroup /app /var/log /var/lib/nginx /run/nginx /etc/nginx /tmp

USER appuser

# Expose Nginx port (8000) and Microservice ports
EXPOSE 8000 8001 8003 8004 8005 8006 8007

# Healthcheck now hits the Nginx proxy
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]