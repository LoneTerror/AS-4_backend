# =========================
# STAGE 1 — BUILDER
# =========================
FROM python:3.10-slim AS builder

WORKDIR /app

# Install build dependencies with --no-install-recommends to keep the layer small
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl ca-certificates libatomic1 \
    nodejs npm && \
    rm -rf /var/lib/apt/lists/*

# Set up virtual environment
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Copy ONLY requirements first to cache the pip install layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Prisma CLI (Version 6) and clean npm cache
RUN npm install -g prisma@6 && npm cache clean --force

# Copy ONLY the Prisma schema first to cache generation
# (Adjust the path if your schema is in a 'prisma/' directory)
COPY prisma/schema.prisma ./prisma/

ENV XDG_CACHE_HOME="/app/.cache" \
    PRISMA_HOME="/app/.prisma" \
    PRISMA_PY_BINARIES_PATH="/app/prisma_binaries" \
    PRISMA_BINARY_CACHE_DIR="/app/.cache" \
    PRISMA_CLI_BINARY_TARGETS="debian-openssl-3.0.x"

RUN prisma generate --no-engine

# Now copy the rest of the application code
COPY . .

# =========================
# STAGE 2 — RUNTIME
# =========================
FROM python:3.10-slim

WORKDIR /app

# Install ONLY runtime dependencies, add networking tools, and clean apt cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 nginx ca-certificates libatomic1 nodejs npm \
    curl iputils-ping netcat-openbsd dnsutils && \
    rm -rf /var/lib/apt/lists/*

# Install pm2 globally and clean npm cache
RUN npm install -g pm2 && npm cache clean --force

# Create non-root user
RUN addgroup --system appgroup && adduser --system --group appuser

# Copy application and venv from builder
COPY --from=builder --chown=appuser:appgroup /app /app

# CRITICAL FIX: Explicitly create the .pm2 directory and grant ownership
RUN mkdir -p /app/.pm2 && chown -R appuser:appgroup /app/.pm2

# Now switch to the non-root user
USER appuser

# Ensure the Python virtual environment is in the PATH for runtime
ENV PATH="/app/venv/bin:$PATH"

ENV XDG_CACHE_HOME="/app/.cache" \
    PRISMA_HOME="/app/.prisma" \
    PRISMA_PY_BINARIES_PATH="/app/prisma_binaries" \
    PRISMA_BINARY_CACHE_DIR="/app/.cache" \
    PM2_HOME="/app/.pm2"

EXPOSE 8000 8001 8002 8003 8004 8005 8006 8007 8008

CMD ["pm2-runtime", "start", "/app/ecosystem.config.js"]