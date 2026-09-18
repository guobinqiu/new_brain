FROM ghcr.io/astral-sh/uv:python3.12-bookworm

WORKDIR /app

ARG USE_CN_MIRROR=false
ARG UV_DEFAULT_INDEX_CN=https://pypi.tuna.tsinghua.edu.cn/simple
ARG UV_HTTP_TIMEOUT=120

ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV UV_HTTP_TIMEOUT=${UV_HTTP_TIMEOUT}

RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
      sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources; \
    fi && \
    apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY services/llm/pyproject.toml services/llm/uv.lock /app/services/llm/
RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
      cd /app/services/llm && UV_DEFAULT_INDEX="$UV_DEFAULT_INDEX_CN" uv sync --no-install-project; \
    else \
      cd /app/services/llm && uv sync --no-install-project; \
    fi

COPY services/__init__.py /app/services/__init__.py
COPY services/llm/__init__.py /app/services/llm/__init__.py
COPY services/llm/pytest.ini /app/services/llm/pytest.ini

CMD ["/app/.venv/bin/uvicorn", "services.llm.src.main:app", "--host", "0.0.0.0", "--port", "6001", "--reload"]
