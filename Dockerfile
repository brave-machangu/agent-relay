# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Pinned to the uv version used locally, so it reads uv.lock the same way.
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    RELAY_DATABASE_URL="sqlite:////data/agent-relay.db"

WORKDIR /app

# Install dependencies first so this layer is cached until uv.lock changes.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# SQLite does not create parent directories; /data is the volume mount point.
RUN useradd --create-home --uid 1000 relay \
    && mkdir -p /data \
    && chown relay:relay /data
USER relay
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
