# MCP-сервер и индексатор документации ИТС. Краулер (Selenium/Chrome) в образе не запускается:
# документация скачивается на хосте (uv run its-parser ...) и монтируется в /data/out.

# === Build stage ===
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# зависимости отдельным слоем (кэшируется, пока не менялись pyproject/uv.lock)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra rag --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --extra rag --no-editable


# === Runtime stage ===
FROM python:3.12-slim

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin its && \
    mkdir -p /data/out /data/models && chown -R its:its /data

COPY --from=builder --chown=its:its /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    ITS_OUT_DIR=/data/out \
    ITS_DATA_DIR=/data \
    ITS_MODELS_CACHE=/data/models \
    ITS_MCP_HOST=0.0.0.0 \
    ITS_MCP_PORT=8080

USER its
WORKDIR /home/its

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8080), timeout=4).close()"

CMD ["sh", "-c", "its-index --all && its-mcp --transport http --host 0.0.0.0 --port 8080"]
