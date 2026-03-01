# =========================
# STAGE 1 — BUILDER
# =========================
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc libpq-dev curl ca-certificates libatomic1 \
    nodejs npm && \
    rm -rf /var/lib/apt/lists/*

RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Generate Prisma client + engine HERE ONLY
RUN prisma generate


# =========================
# STAGE 2 — RUNTIME
# =========================
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq5 supervisor nginx ca-certificates libatomic1 && \
    rm -rf /var/lib/apt/lists/*

# Copy entire built app
COPY --from=builder /app /app

# Create non-root user
RUN addgroup --system appgroup && adduser --system --group appuser

RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000 8001 8003 8004 8005 8006 8007

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]