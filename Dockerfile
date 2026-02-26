# ---------- STAGE 1: BUILDER ----------
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system deps + Node.js (Required for Prisma to generate without downloading engines)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Setup Virtual Environment
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Generate Prisma Client 
# Since Node.js is now installed in the OS, Prisma won't try to download it.
COPY prisma/schema.prisma ./prisma/
RUN prisma generate

# ---------- STAGE 2: RUNTIME ----------
FROM python:3.11-slim

# Create non-root user
RUN addgroup --system appgroup && adduser --system --group appuser

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/venv \
    PATH="/app/venv/bin:$PATH" \
    HOME="/app"

WORKDIR /app

# Install ONLY runtime dependencies (no gcc, no nodejs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the venv (including generated prisma client) from builder
COPY --from=builder /app/venv /app/venv
# Copy the schema (prisma needs it at runtime)
COPY --from=builder /app/prisma /app/prisma

# Copy source code
COPY . .

# Set permissions
RUN chown -R appuser:appgroup /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["gunicorn", "src.main:app", \
     "--workers", "2", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "60"]