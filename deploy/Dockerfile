# syntax=docker/dockerfile:1.7
FROM docker:29.1.2-cli AS docker-cli
FROM ghcr.io/astral-sh/uv:python3.11-bookworm AS base

ARG USE_CN_MIRROR=false
ARG APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG APT_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
ARG UV_DEFAULT_INDEX_CN=https://pypi.tuna.tsinghua.edu.cn/simple
ARG UV_HTTP_TIMEOUT=120

ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV UV_HTTP_TIMEOUT=${UV_HTTP_TIMEOUT}

RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
  sed -i \
  -e "s|http://deb.debian.org/debian-security|${APT_SECURITY_MIRROR}|g" \
  -e "s|http://deb.debian.org/debian|${APT_MIRROR}|g" \
  /etc/apt/sources.list.d/debian.sources; \
  fi \
  && apt-get update -o Acquire::Retries=5 -o Acquire::http::Timeout=30 \
  && apt-get install -y --no-install-recommends --fix-missing \
  -o Acquire::Retries=5 \
  -o Acquire::http::Timeout=30 \
  libgl1 \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN mkdir -p /app/services/rag /app/services/parser /app/services/inference /app/services/ops /app/services/llm

FROM base AS rag
RUN --mount=type=bind,source=services/rag/pyproject.toml,target=/app/services/rag/pyproject.toml,readonly \
  --mount=type=bind,source=services/rag/uv.lock,target=/app/services/rag/uv.lock,readonly \
  if [ "$USE_CN_MIRROR" = "true" ]; then \
  cd /app/services/rag && UV_DEFAULT_INDEX="$UV_DEFAULT_INDEX_CN" uv sync --frozen --no-install-project; \
  else \
  cd /app/services/rag && uv sync --frozen --no-install-project; \
  fi
CMD ["/app/.venv/bin/uvicorn", "services.rag.app.main:app", "--host", "0.0.0.0", "--port", "6000", "--reload"]

FROM base AS ops
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
RUN --mount=type=bind,source=services/ops/pyproject.toml,target=/app/services/ops/pyproject.toml,readonly \
  --mount=type=bind,source=services/ops/uv.lock,target=/app/services/ops/uv.lock,readonly \
  if [ "$USE_CN_MIRROR" = "true" ]; then \
  cd /app/services/ops && UV_DEFAULT_INDEX="$UV_DEFAULT_INDEX_CN" uv sync --frozen --no-install-project; \
  else \
  cd /app/services/ops && uv sync --frozen --no-install-project; \
  fi
CMD ["/app/.venv/bin/uvicorn", "services.ops.app.main:app", "--host", "0.0.0.0", "--port", "7002", "--reload"]

FROM base AS parser
RUN apt-get update -o Acquire::Retries=5 -o Acquire::http::Timeout=30 \
  && apt-get install -y --no-install-recommends --fix-missing \
  -o Acquire::Retries=5 \
  -o Acquire::http::Timeout=30 \
  libreoffice \
  && rm -rf /var/lib/apt/lists/*
RUN --mount=type=bind,source=services/parser/pyproject.toml,target=/app/services/parser/pyproject.toml,readonly \
  --mount=type=bind,source=services/parser/uv.lock,target=/app/services/parser/uv.lock,readonly \
  if [ "$USE_CN_MIRROR" = "true" ]; then \
  cd /app/services/parser && UV_DEFAULT_INDEX="$UV_DEFAULT_INDEX_CN" uv sync --frozen --no-install-project; \
  else \
  cd /app/services/parser && uv sync --frozen --no-install-project; \
  fi
CMD ["/app/.venv/bin/uvicorn", "services.parser.app.main:app", "--host", "0.0.0.0", "--port", "7000", "--reload"]

FROM base AS inference
ARG SERVICE_EXTRA=cpu
RUN --mount=type=bind,source=services/inference/pyproject.toml,target=/app/services/inference/pyproject.toml,readonly \
  --mount=type=bind,source=services/inference/uv.lock,target=/app/services/inference/uv.lock,readonly \
  if [ "$USE_CN_MIRROR" = "true" ]; then \
  cd /app/services/inference && UV_DEFAULT_INDEX="$UV_DEFAULT_INDEX_CN" uv sync --frozen --no-install-project --extra "$SERVICE_EXTRA"; \
  else \
  cd /app/services/inference && uv sync --frozen --no-install-project --extra "$SERVICE_EXTRA"; \
  fi
CMD ["/app/.venv/bin/uvicorn", "services.inference.app.main:app", "--host", "0.0.0.0", "--port", "7001", "--reload"]

FROM base AS llm
RUN --mount=type=bind,source=services/llm/pyproject.toml,target=/app/services/llm/pyproject.toml,readonly \
  --mount=type=bind,source=services/llm/uv.lock,target=/app/services/llm/uv.lock,readonly \
  if [ "$USE_CN_MIRROR" = "true" ]; then \
  cd /app/services/llm && UV_DEFAULT_INDEX="$UV_DEFAULT_INDEX_CN" uv sync --frozen --no-install-project; \
  else \
  cd /app/services/llm && uv sync --frozen --no-install-project; \
  fi

COPY services/__init__.py /app/services/__init__.py
COPY services/llm/__init__.py /app/services/llm/__init__.py
COPY services/llm/pytest.ini /app/services/llm/pytest.ini

CMD ["/app/.venv/bin/uvicorn", "services.llm.src.main:app", "--host", "0.0.0.0", "--port", "6001", "--reload"]
