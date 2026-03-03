# =============================================================================
# FORTRESS PRIME — Unified Service Image
# =============================================================================
# Single image for all Fortress Python services. Each docker-compose service
# overrides CMD to run a different entrypoint.
#
# Build:
#   docker build -t fortress-prime .
#
# Usage:
#   docker run fortress-prime python3 -m uvicorn gateway.app:app ...   (gateway)
#   docker run fortress-prime supercronic /app/scheduler/crontab        (scheduler)
#   docker run fortress-prime python3 src/bridges/groundskeeper_shadow.py (one-shot)
# =============================================================================

FROM python:3.12-slim AS base

# System deps: postgres client, curl for healthchecks, supercronic for scheduling
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client \
        curl \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Install supercronic (cron replacement for containers)
# Detect arch at build time: amd64 or arm64
RUN ARCH=$(dpkg --print-architecture) && \
    curl -fsSL -o /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/v0.2.33/supercronic-linux-${ARCH}" && \
    chmod +x /usr/local/bin/supercronic

WORKDIR /app

# Python deps (cached layer — only rebuilds when requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || \
    pip install --no-cache-dir \
        fastapi uvicorn[standard] python-multipart pydantic \
        psycopg2-binary python-dotenv requests pyyaml psutil \
        python-jose[cryptography] bcrypt \
        langchain langchain-core langchain-community \
        'chromadb>=1.1.0,<2.0.0' \
        plaid-python plotly pypdf numpy pandas pillow

# Copy full project (use .dockerignore to exclude __pycache__, .git, etc.)
COPY . /app/

# Ensure project root is on PYTHONPATH
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Default: gateway (overridden per service in docker-compose)
EXPOSE 8000
ENTRYPOINT ["tini", "--"]
CMD ["python3", "-m", "uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
