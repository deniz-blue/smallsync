FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1
WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen
COPY schemas /app/schemas
COPY server/smallsync_server ./smallsync_server
ENV SMALLSYNC_DATA=/data SMALLSYNC_ACCESS=/config/access.json
EXPOSE 8080
CMD [".venv/bin/uvicorn", "smallsync_server.app:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-graceful-shutdown", "5"]
