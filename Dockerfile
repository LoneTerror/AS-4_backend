# =========================
# STAGE 1 — BUILDER
# =========================
FROM python:3.10-slim AS builder

WORKDIR /app

# 1. Install OpenSSL (Fixes the warning) and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl ca-certificates openssl libatomic1 \
    && rm -rf /var/lib/apt/lists/*

# 2. Setup Virtual Env
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
RUN pip install --upgrade pip

ENV PRISMA_CLIENT_PY_ENGINE_TYPE="binary"

# 3. Install Python Dependencies
# (Ensure 'prisma' is in your requirements.txt)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Generate Prisma Client (Using Python's built-in Prisma CLI)
COPY prisma/ ./prisma/
ENV PRISMA_BINARY_CACHE_DIR="/app/.cache/prisma-python"
# This fixes the "prisma-client-py not found" error
RUN prisma generate && rm -rf /app/.cache/prisma-python

# 5. Copy the rest of the application code
COPY . .

# =========================
# STAGE 2 — RUNTIME
# =========================
FROM python:3.10-slim

WORKDIR /app

# 1. Install runtime dependencies (As Root)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 ca-certificates openssl libatomic1 \
    && rm -rf /var/lib/apt/lists/*

# 2. Create user and group (As Root)
RUN addgroup --system appgroup && adduser --system --group appuser

# 3. Copy app from builder
# We use --chown here, but we will also do a recursive chown to be safe
COPY --from=builder /app /app

# 4. Create logs directory AND fix all permissions (As Root)
# We do this BEFORE switching to the limited user
RUN mkdir -p /app/logs && \
    chown -R appuser:appgroup /app && \
    chmod -R 755 /app/logs

# 5. Environment variables
ENV PATH="/app/venv/bin:$PATH"
ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1
ENV PRISMA_BINARY_CACHE_DIR="/app/.cache/prisma-python"

# 6. NOW switch to the limited user
USER appuser

# Fallback CMD
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]