FROM ghcr.io/astral-sh/uv:python3.10-bookworm

ARG USE_CN_MIRROR=false
ARG APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG APT_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
ARG UV_DEFAULT_INDEX_CN=https://pypi.tuna.tsinghua.edu.cn/simple
ARG UV_HTTP_TIMEOUT=120

ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV UV_HTTP_TIMEOUT=${UV_HTTP_TIMEOUT}
ENV UV_SKIP_WHEEL_FILENAME_CHECK=1
ENV LD_LIBRARY_PATH=/opt/rivs/lib:${LD_LIBRARY_PATH}

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

COPY deploy/ecu/pyproject.toml /app/rag/pyproject.toml
COPY --from=ecu_wheels . /tmp/ecu_wheels
RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
        cd /app/rag && UV_DEFAULT_INDEX="$UV_DEFAULT_INDEX_CN" uv sync --no-install-project; \
    else \
        cd /app/rag && uv sync --no-install-project; \
    fi \
    && uv pip install --no-deps /tmp/ecu_wheels/*.whl \
    && rm -rf /tmp/ecu_wheels

COPY deploy/ecu/bootstrap.py /app/ecu/bootstrap.py

CMD ["/app/.venv/bin/python", "/app/ecu/bootstrap.py"]
