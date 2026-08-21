FROM ghcr.io/astral-sh/uv:python3.11-bookworm

ARG USE_CN_MIRROR=false
ARG APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG APT_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
ARG UV_DEFAULT_INDEX_CN=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/app/.venv

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

WORKDIR /app/backend

COPY backend/pyproject.toml backend/uv.lock ./
RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
        UV_DEFAULT_INDEX="$UV_DEFAULT_INDEX_CN" uv sync --extra cpu; \
    else \
        uv sync --extra cpu; \
    fi

CMD ["/app/.venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6000", "--reload"]
