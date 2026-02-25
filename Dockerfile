# Use a slim Python image to reduce size and vulnerabilities
FROM python:3.11-slim

# Create a non-root user and group
RUN addgroup --system appgroup && adduser --system --group appuser

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# --- FIX START: Force Prisma to use a folder inside /app for binaries ---
# This prevents the "Permission denied: /root/.cache/..." error
ENV PRISMA_PY_CACHE_DIR="/app/prisma_cache"
# --- FIX END ---

WORKDIR /app

# Install system dependencies required for PostgreSQL and Prisma
# We clean up apt lists to keep the image small
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire codebase
COPY . .

# Generate the Prisma Client
# Because of the ENV var above, binaries will now save to /app/prisma_cache
RUN python -m prisma generate

# Hand over directory ownership to the non-root user
# This now COVERS the new /app/prisma_cache directory too!
RUN chown -R appuser:appgroup /app

# Drop root privileges
USER appuser

EXPOSE 8000

# Start Gunicorn
CMD ["gunicorn", "src.main:app", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]