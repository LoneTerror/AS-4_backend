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

# Install ONLY runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 ca-certificates libatomic1 \
    curl iputils-ping netcat-openbsd dnsutils \
    && rm -rf /var/lib/apt/lists/*

# Security: Non-root user
RUN addgroup --system appgroup && adduser --system --group appuser

# Copy app from builder
COPY --from=builder --chown=appuser:appgroup /app /app

# CRITICAL: Fix the Python path so it can find the 'src' folder
ENV PYTHONPATH=/app
ENV PRISMA_BINARY_CACHE_DIR="/app/.cache/prisma-python"
ENV PYTHONUNBUFFERED=1

# Ensure the venv is at the FRONT of the path
ENV PATH="/app/venv/bin:$PATH"
# Explicitly tell Python where the site-packages are
ENV PYTHONPATH="/app:/app/venv/lib/python3.10/site-packages"

USER appuser

# FALLBACK COMMAND: This will be overridden by K8s args
# If no args are provided, it tries to run the root main.py
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]