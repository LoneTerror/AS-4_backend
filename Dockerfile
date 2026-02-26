# ---------- BASE ----------
FROM python:3.11-slim

# Create non-root user
RUN addgroup --system appgroup && adduser --system --group appuser

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV VIRTUAL_ENV=/app/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV PRISMA_PY_CACHE_DIR="/app/prisma_cache"
ENV HOME="/app"

WORKDIR /app

# Install build deps (removed later)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv $VIRTUAL_ENV

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create Prisma cache
RUN mkdir -p /app/prisma_cache

# Generate Prisma Client
COPY schema.prisma . 
RUN prisma generate && rm -rf /app/.npm /root/.npm

# Remove build-only packages (reduce image size + RAM)
RUN apt-get purge -y gcc && apt-get autoremove -y

# Fix permissions
RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# Healthcheck (used by Docker / Compose / Jenkins)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Gunicorn tuned for low RAM
CMD ["gunicorn", "src.main:app", \
     "--workers", "2", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "60"]