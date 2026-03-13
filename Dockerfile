# =========================
# STAGE 1 — BUILDER
# =========================
FROM python:3.10-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl ca-certificates libatomic1 \
    nodejs npm && \
    rm -rf /var/lib/apt/lists/*

RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
RUN pip install --upgrade pip

COPY requirements.txt .
# Pip will now verify hashes for every package
RUN pip install --no-cache-dir -r requirements.txt

# Install Prisma CLI
RUN npm install -g prisma@6 && npm cache clean --force

# COPY SCHEMA BEFORE GENERATE
COPY prisma/schema.prisma ./prisma/

# CRITICAL: Force Prisma to generate binaries into /app instead of /root
ENV PRISMA_BINARY_CACHE_DIR="/app/.cache/prisma-python"
ENV PRISMA_CLI_BINARY_TARGETS="debian-openssl-3.0.x"

RUN prisma generate

# Copy the rest of the application
COPY . .

# =========================
# STAGE 2 — RUNTIME
# =========================
FROM python:3.10-slim

WORKDIR /app

# Install runtime dependencies + procps for PM2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 ca-certificates libatomic1 nodejs npm nginx procps \
    curl iputils-ping netcat-openbsd dnsutils && \
    npm install -g pm2 && \
    npm cache clean --force && \
    # We keep nginx, but we can remove npm to save space
    apt-get purge -y npm && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Security: Non-root user
RUN addgroup --system appgroup && adduser --system --group appuser

# Copy app from builder (includes the /app/.cache/prisma-python folder)
COPY --from=builder --chown=appuser:appgroup /app /app

# Ensure PM2 and Logs directories are writable by appuser
RUN mkdir -p /app/.pm2 /app/logs /tmp/nginx && \
    chown -R appuser:appgroup /app/.pm2 /app/logs /var/lib/nginx /var/log/nginx /tmp/nginx

USER appuser
ENV PATH="/app/venv/bin:$PATH"
ENV PM2_HOME="/app/.pm2"
# Ensure the app knows where to find the binaries at runtime
ENV PRISMA_BINARY_CACHE_DIR="/app/.cache/prisma-python"

EXPOSE 8000

CMD ["pm2-runtime", "start", "ecosystem.config.js"]