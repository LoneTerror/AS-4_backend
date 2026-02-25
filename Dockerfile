# Use a slim Python image
FROM python:3.11-slim

# Create a non-root user and group
RUN addgroup --system appgroup && adduser --system --group appuser

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# --- CONFIGURATION START ---
# 1. Set up the Virtual Environment path
ENV VIRTUAL_ENV=/app/venv
# 2. Add the venv to the PATH. This "activates" it by default for all future commands.
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
# 3. Force Prisma to use a folder inside /app for binaries (Fixes the permission crash)
ENV PRISMA_PY_CACHE_DIR="/app/prisma_cache"
# 4. Set HOME to /app so other tools cache correctly
ENV HOME="/app"
# --- CONFIGURATION END ---

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# --- VENV CREATION ---
# Create the virtual environment
RUN python -m venv $VIRTUAL_ENV

# Install Python dependencies (These now automatically go into the venv because of PATH)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the codebase
COPY . .

# Generate the Prisma Client (Uses the venv's python and stores cache in /app/prisma_cache)
RUN mkdir -p /app/prisma_cache
RUN python -m prisma generate

# --- PERMISSIONS FIX ---
# Hand over ownership of the ENTIRE app directory (code, venv, and prisma cache) to appuser
RUN chown -R appuser:appgroup /app

# Drop root privileges
USER appuser

EXPOSE 8000

# Start Gunicorn (It will use the gunicorn installed inside the venv)
CMD ["gunicorn", "src.main:app", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]