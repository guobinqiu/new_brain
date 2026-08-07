# RAG Knowledge Search

## Native 启动

Native 方式只把后端和前端跑在宿主机上，默认仍使用 Docker 启动 Qdrant 数据库服务。

1. 启动 Qdrant：

```bash
docker compose -f deploy/cpu/docker-compose.yml up -d qdrant
```

2. 启动后端：

```bash
cd backend
CONFIG_FILE=default.yaml .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

3. 启动前端：

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5175
```

访问地址：

```text
http://localhost:5175
```

## Docker 启动

默认使用 CPU 版 Docker 配置：

```bash
just deploy build
just deploy up
```

停止：

```bash
just deploy down
```

重启：

```bash
just deploy down up
```

Docker 前端访问地址：

```text
http://localhost:5175
```

## 配置文件

后端通过 `CONFIG_FILE` 选择配置文件，配置文件位于 `backend/config/`。

Native 默认配置：

```bash
CONFIG_FILE=default.yaml
```

Docker 默认配置：

```bash
CONFIG_FILE=docker.yaml
```

临时切换配置示例：

```bash
CONFIG_FILE=milvus.yaml .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

## 数据目录

本地数据目录按数据库产品分组：

```text
qdrant_data/
  docker/

chroma_data/
  native/
  docker/

milvus_data/
  standalone/
  lite/
    native/
    docker/
```

Chroma local 和 Milvus Lite 是嵌入式文件库，native 和 Docker 使用不同子目录，避免两个运行环境同时读写同一份文件。
