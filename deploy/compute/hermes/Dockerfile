ARG CUDA_IMAGE=nvidia/cuda:13.0.0-runtime-ubuntu22.04
FROM ${CUDA_IMAGE}

ARG HERMES_UID=1000
ARG HERMES_GID=1000

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    git \
    libpq-dev \
    python3.11 \
    python3.11-dev \
    python3.11-venv \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid "${HERMES_GID}" hermes \
    && useradd --uid "${HERMES_UID}" --gid "${HERMES_GID}" --create-home --shell /bin/bash hermes

WORKDIR /app

COPY backend/requirements.txt /tmp/requirements.txt

RUN python3.11 -m venv "${VIRTUAL_ENV}" \
    && pip install --upgrade pip setuptools wheel

RUN python3.11 -c "from pathlib import Path; source = Path('/tmp/requirements.txt'); filtered = [line for line in source.read_text(encoding='utf-8').splitlines() if not line.strip().startswith(('ray[default]==', 'ray[serve]==', 'vllm=='))]; Path('/tmp/requirements.hermes.txt').write_text('\\n'.join(filtered) + '\\n', encoding='utf-8')"

RUN pip install -r /tmp/requirements.hermes.txt \
    && pip install psycopg2-binary python-docx structlog tenacity

RUN mkdir -p /app/docs/paperclip /app/memory \
    && chown -R hermes:hermes /app /opt/venv

COPY --chown=hermes:hermes . /app/fortress-guest-platform

WORKDIR /app/fortress-guest-platform

USER hermes

EXPOSE 8100

CMD ["uvicorn", "hermes_app:app", "--host", "0.0.0.0", "--port", "8100"]
