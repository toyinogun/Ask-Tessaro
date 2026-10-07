# syntax=docker/dockerfile:1
# Build from the repo root: docker build -f services/zulip-adapter/Dockerfile .
FROM ghcr.io/astral-sh/uv:0.12.23 AS uv

FROM python:3.13-slim AS builder
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock .python-version ./
COPY libs ./libs
COPY services ./services
RUN uv sync --package zulip-adapter --locked --no-dev --no-editable

FROM python:3.13-slim
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid 10001 --no-create-home app
COPY --from=builder /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8080
CMD ["uvicorn", "tessaro_zulip_adapter.main:app", "--host", "0.0.0.0", "--port", "8080"]
