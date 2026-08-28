FROM ghcr.io/astral-sh/uv:python3.11-bookworm

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
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY rag/pyproject.toml rag/uv.lock /app/rag/
RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
        cd /app/rag && UV_DEFAULT_INDEX="$UV_DEFAULT_INDEX_CN" uv sync --no-install-project --extra gpu; \
    else \
        cd /app/rag && uv sync --no-install-project --extra gpu; \
    fi

CMD ["/app/.venv/bin/uvicorn", "rag.main:app", "--host", "0.0.0.0", "--port", "6000", "--reload"]
