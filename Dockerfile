# =========================
# STAGE 1 — BUILDER
# =========================
FROM python:3.10-slim AS builder

WORKDIR /app

# Install build dependencies + Node.js (strictly for Prisma CLI generation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl ca-certificates libatomic1 \
    nodejs npm && \
    rm -rf /var/lib/apt/lists/*

RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
RUN pip install --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Prisma CLI
RUN npm install -g prisma@6 && npm cache clean --force

# Copy Prisma schema
COPY prisma/schema.prisma ./prisma/

# CRITICAL: Force Prisma to generate binaries into /app
ENV PRISMA_BINARY_CACHE_DIR="/app/.cache/prisma-python"
ENV PRISMA_CLI_BINARY_TARGETS="debian-openssl-3.0.x"

# Generate Prisma Client
RUN prisma generate

# Copy the rest of the application code
COPY . .

# =========================
# STAGE 2 — RUNTIME
# =========================
FROM python:3.10-slim

WORKDIR /app

# Install ONLY runtime dependencies. 
# PM2, Node.js, npm, and Nginx are REMOVED.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 ca-certificates libatomic1 \
    curl iputils-ping netcat-openbsd dnsutils && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Security: Non-root user
RUN addgroup --system appgroup && adduser --system --group appuser

# Copy app from builder (includes the /app/.cache/prisma-python folder and venv)
COPY --from=builder --chown=appuser:appgroup /app /app

# Create a generic logs directory
RUN mkdir -p /app/logs && chown -R appuser:appgroup /app/logs

USER appuser
ENV PATH="/app/venv/bin:$PATH"
ENV PRISMA_BINARY_CACHE_DIR="/app/.cache/prisma-python"

EXPOSE 8000

# We DO NOT define a strict CMD here anymore.
# The command will be injected by docker-compose.yml for each specific service.
CMD ["python", "-m", "uvicorn", "src.core.main:app", "--host", "0.0.0.0", "--port", "8000"]