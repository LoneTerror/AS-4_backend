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

# 1. Install system dependencies (Rarely changes)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 2. Setup Venv and Install Python deps (Changes only when requirements.txt changes)
RUN python -m venv $VIRTUAL_ENV
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Generate Prisma Client (Changes only when schema changes)
# This is the "Heavy" layer we want to protect with caching
COPY prisma/schema.prisma ./prisma/
RUN prisma generate && rm -rf /app/.npm /root/.npm 

# 4. Copy source code (Changes MOST often - keep it near the bottom)
COPY . .

# 5. Cleanup and Permissions
RUN mkdir -p /app/prisma_cache && \
    apt-get purge -y gcc && \
    apt-get autoremove -y && \
    chown -R appuser:appgroup /app

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["gunicorn", "src.main:app", \
     "--workers", "2", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "60"]