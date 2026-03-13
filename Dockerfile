# =========================
# STAGE 1 — BUILDER
# =========================
FROM python:3.10-slim AS builder

WORKDIR /app

# Added libatomic1 and kept dependencies lean
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl ca-certificates libatomic1 \
    nodejs npm && \
    rm -rf /var/lib/apt/lists/*

# Set up virtual environment
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# UPGRADE PIP: Essential for --require-hashes mode
RUN pip install --upgrade pip

# Copy ONLY requirements first
COPY requirements.txt .
# Pip will now verify hashes for every package
RUN pip install --no-cache-dir -r requirements.txt

# Install Prisma CLI
RUN npm install -g prisma@6 && npm cache clean --force

# Copy schema and generate client
COPY prisma/schema.prisma ./prisma/

# Ensure Prisma binaries are accessible
ENV PRISMA_CLI_BINARY_TARGETS="debian-openssl-3.0.x"
RUN prisma generate

# Copy the rest of the application
COPY . .

# =========================
# STAGE 2 — RUNTIME
# =========================
FROM python:3.10-slim

WORKDIR /app

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

# Copy app from builder
COPY --from=builder --chown=appuser:appgroup /app /app

# Ensure logs and pm2 home exist
RUN mkdir -p /app/.pm2 /app/logs && chown -R appuser:appgroup /app/.pm2 /app/logs

USER appuser
ENV PATH="/app/venv/bin:$PATH"
ENV PM2_HOME="/app/.pm2"

EXPOSE 8000

# Using pm2-runtime for Docker-native process management
CMD ["pm2-runtime", "start", "ecosystem.config.js"]