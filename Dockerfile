# ---------- STAGE 1: BUILDER ----------
FROM python:3.11-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY prisma/schema.prisma ./prisma/
RUN prisma generate

# ---------- STAGE 2: RUNTIME ----------
# ---------- STAGE 2: RUNTIME ----------
FROM python:3.11-slim
RUN addgroup --system appgroup && adduser --system --group appuser
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 VIRTUAL_ENV=/app/venv PATH="/app/venv/bin:$PATH" HOME="/app"
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl supervisor nginx && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/venv /app/venv
COPY --from=builder /app/prisma /app/prisma

COPY . .
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# REMOVE default Nginx configs and use the custom one
RUN rm -f /etc/nginx/nginx.conf /etc/nginx/sites-enabled/default
COPY nginx.conf /etc/nginx/nginx.conf

# PERMISSIONS: Critical for non-root Nginx
RUN mkdir -p /var/log/nginx /var/lib/nginx /run/nginx /tmp/client_temp && \
    chown -R appuser:appgroup /app /var/log/nginx /var/lib/nginx /run/nginx /etc/nginx /tmp

USER appuser
EXPOSE 8000 8001 8003 8004 8005 8006 8007

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]