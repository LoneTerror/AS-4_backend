# Use a slim Python image to reduce size and vulnerabilities
FROM python:3.11-slim

# Create a non-root user and group
RUN addgroup --system appgroup && adduser --system --group appuser

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies required for PostgreSQL and Prisma
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire modular monolith codebase
COPY . .

# CRITICAL STEP: Generate the Prisma Client
# This reads your schema.prisma file and builds the Python client
RUN python -m prisma generate

# Hand over directory ownership to the non-root user
RUN chown -R appuser:appgroup /app

# Drop root privileges
USER appuser

EXPOSE 8000

# Start Gunicorn. 
# Note: Since your main.py uses relative imports (.rewards), 
# ensure the module path aligns with your directory structure.
CMD ["gunicorn", "src.main:app", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]