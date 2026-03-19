# =========================
# STAGE 0 — PRISMA BUILDER
# =========================
FROM node:18-slim AS prisma-builder

WORKDIR /app

# Install prisma only once (cached)
RUN npm install -g prisma@6

# Copy only schema (IMPORTANT for caching)
COPY prisma/schema.prisma ./prisma/

# Generate client
RUN prisma generate


# =========================
# STAGE 1 — BUILDER
# =========================
FROM python:3.10-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl ca-certificates libatomic1 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ... [STAGE 0 & STAGE 1 STAY THE SAME] ...

# =========================
# STAGE 2 — RUNTIME
# =========================
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 ca-certificates libatomic1 \
    && rm -rf /var/lib/apt/lists/*

# Create the user and group first
RUN addgroup --system appgroup && adduser --system --group appuser

# 1. Fix Permissions during COPY (CRITICAL)
# This ensures appuser owns the code and the virtual environment
COPY --from=builder --chown=appuser:appgroup /app /app

# 2. Copy Prisma client with correct ownership
COPY --from=prisma-builder --chown=appuser:appgroup /app/node_modules/.prisma /app/.prisma
COPY --from=prisma-builder --chown=appuser:appgroup /app/node_modules/@prisma /app/@prisma

# Ensure the logs directory exists and is writable if you ever enable LOG_TO_FILE
RUN mkdir -p /app/logs && chown -R appuser:appgroup /app/logs

ENV PATH="/app/venv/bin:$PATH"
ENV PYTHONPATH="/app:/app/venv/lib/python3.10/site-packages"
ENV PYTHONUNBUFFERED=1

USER appuser

# Fallback CMD
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]