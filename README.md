# RAG Knowledge Search

## Native 启动

Native 方式只把后端和前端跑在宿主机上，默认仍使用 Docker 启动 Qdrant 和 MinIO。

1. 启动 Qdrant 和 MinIO：

```bash
docker compose -f deploy/cpu/docker-compose.yml up -d qdrant minio
```

2. 启动后端：

```bash
cd backend
S3_ENDPOINT_URL=http://localhost:19000 CONFIG_FILE=local.yaml .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
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

CPU 版：

```bash
just deploy cpu build
just deploy cpu up
```

停止：

```bash
just deploy cpu down
```

重启：

```bash
just deploy cpu restart
```

GPU 版：

```bash
just deploy gpu build
just deploy gpu up
```

国内网络构建时可以加镜像开关：

```bash
USE_CN_MIRROR=true just deploy cpu build
USE_CN_MIRROR=true just deploy gpu build
```

停止：

```bash
just deploy gpu down
```

重启：

```bash
just deploy gpu restart
```

Docker 前端访问地址：

```text
http://<服务器地址>:5175
```

Docker 后端 API 地址：

```text
http://<服务器地址>:28000
```

## API

外部系统只需要调用知识写入、知识查询、文档列表和文档删除接口。健康检查和运行时配置接口属于内部运维接口，这里不列入外部集成 API。

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/upload` | 上传文档到对象存储，返回 `s3_url` 和 `filename` |
| `POST` | `/api/presign` | 根据 `s3_url` 生成短期下载 URL |
| `POST` | `/api/index` | 从对象存储预签名 URL 读取文档，同步写入索引后返回 `file_id` |
| `POST` | `/api/search` | 搜索知识库 |
| `GET` | `/api/files` | 查询文件聚合列表 |
| `GET` | `/api/chunks` | 查询向量 chunk 列表 |
| `DELETE` | `/api/files/{file_id}` | 删除文件及其 chunks |

### 上传文档

`POST /api/upload`

请求类型：`multipart/form-data`

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `file` | file | 是 | - | 支持 `.pdf`、`.txt`、`.md`、`.markdown`、`.docx`、`.png`、`.jpg`、`.jpeg`、`.webp`、`.bmp` |

响应示例：

```json
{
  "s3_url": "s3://rag-dev/uploads/550e8400e29b41d4a716446655440000/example.pdf",
  "filename": "example.pdf"
}
```

该接口返回对象存储地址。需要建立索引时，继续调用 `POST /api/presign` 和 `POST /api/index`。

### 签名对象存储文件

`POST /api/presign`

请求类型：`application/json`

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `s3_url` | string | 是 | - | 稳定对象存储地址，例如 `s3://bucket/key` |
| `expires_in` | int | 否 | `3600` | 签名有效期，单位秒，范围 `60..86400` |

响应示例：

```json
{
  "presigned_url": "http://minio:9000/rag-dev/uploads/example.pdf?..."
}
```

### 索引对象存储文件

`POST /api/index`

请求类型：`application/json`

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `file_id` | string | 否 | 后端生成 | 上游文件 ID；传了会覆盖该 `file_id` 的旧 chunks，不传则由 RAG 生成 |
| `presigned_url` | string | 是 | - | 本次索引用的一次性下载 URL，不保存到索引 |
| `s3_url` | string | 是 | - | 稳定对象存储地址，例如 `s3://bucket/key`，写入 metadata 用于追溯 |
| `filename` | string | 否 | 从 `s3_url` 推导 | 自定义展示文件名 |

请求示例：

```json
{
  "file_id": "upstream-file-001",
  "presigned_url": "https://example.com/presigned",
  "s3_url": "s3://bucket/path/to/example.pdf"
}
```

响应示例：

```json
{
  "file_id": "upstream-file-001"
}
```

`file_id` 推荐由上游系统保存映射关系。上游传入 `file_id` 时，RAG 会先删除该 `file_id` 的旧 chunks，再写入新 chunks；上游不传时，RAG 生成一个 32 位 hex ID。`s3_url` 会写入 chunk metadata，用于追溯对象存储来源。

Docker 开发环境内置 MinIO 用来模拟 S3，控制台是 `http://localhost:19001`。后端会提供本地联调用的 `POST /api/presign`：输入 `s3_url`，返回后端可访问的短期下载地址，再用该 URL 调用 `POST /api/index`。生产环境由上游系统或对象存储网关负责重签，RAG 只依赖 `presigned_url + s3_url`。

Docker 启动时后端使用容器内地址：

```text
S3_ENDPOINT_URL=http://minio:9000
S3_BUCKET=rag-dev
```

Native 本地启动时需要把 `S3_ENDPOINT_URL` 配成当前后端进程可访问的 MinIO 地址，例如：

```bash
S3_ENDPOINT_URL=http://localhost:19000 CONFIG_FILE=local.yaml backend/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

前端上传文件时按三步串行执行：

```text
POST /api/upload -> POST /api/presign -> POST /api/index
```

### 搜索

`POST /api/search`

请求类型：`application/json`

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `query` | string | 是 | - | 查询内容 |
| `mode` | string | 否 | 配置文件里的 `search.default_mode` | `dense`、`sparse`、`hybrid` |
| `sparse_mode` | string | 否 | `app` | sparse 查询方式，取值为 `/api/config` 返回的 `sparse.available_modes` |
| `top_k` | int | 否 | 配置文件里的 `search.top_k` | 最多返回条数，范围 `1..50` |
| `rerank` | bool | 否 | 当前配置是否启用 rerank 组件 | 是否启用重排 |
| `fetch_k` | int | 否 | 配置文件里的 `search.fetch_k` | 重排候选池，必须大于等于 `top_k` |
| `dense_weight` | number | 否 | 配置文件里的 `search.dense_weight` | 本次 hybrid 查询的 dense 权重 |
| `sparse_weight` | number | 否 | 配置文件里的 `search.sparse_weight` | 本次 hybrid 查询的 sparse 权重 |
| `rrf_k` | int | 否 | 配置文件里的 `search.rrf_k` | 本次 hybrid 查询的 RRF 参数 |
| `file_ids` | string[] | 否 | - | 限定搜索范围；不传表示全量搜索；空数组会被拒绝；最多 1000 个 |

请求示例：

```json
{
  "query": "有多少华为卡",
  "mode": "hybrid",
  "sparse_mode": "app",
  "top_k": 5,
  "rerank": true,
  "fetch_k": 50,
  "dense_weight": 0.5,
  "sparse_weight": 0.5,
  "rrf_k": 60,
  "file_ids": ["upstream-file-001"]
}
```

响应字段：

| 字段 | 说明 |
|---|---|
| `results` | 搜索结果列表 |
| `mode` | 本次搜索模式 |
| `sparse_mode` | 本次 sparse 查询方式 |
| `rerank` | 本次是否启用重排 |
| `fetch_k` | 本次候选池大小 |
| `dense_weight` | 本次 hybrid 查询的 dense 权重 |
| `sparse_weight` | 本次 hybrid 查询的 sparse 权重 |
| `rrf_k` | 本次 hybrid 查询的 RRF 参数 |
| `elapsed_ms` | 后端搜索耗时，单位毫秒 |

### 运行监控

`GET /api/monitor`

响应字段：

| 字段 | 说明 |
|---|---|
| `ready` | 应用是否完成初始化 |
| `profile` | 当前启动 profile，包括配置名和 store 概要 |
| `components` | 当前运行组件列表，包括 Store、Dense、Sparse、Rerank、OCR 的状态和绑定模型 |
| `capabilities` | 当前服务能力，包括搜索模式、sparse 模式、是否支持配置写入和重启 |
| `index_contract` | 索引与存储诊断信息，包括当前 collection、vector sparse 是否已建立等 |
| `data` | 当前文件数、chunk 数和 collection 名 |
| `search_traces` | 最近搜索链路列表，用于诊断单次请求各阶段耗时 |

`components[].status` 有四种状态：`ready` 表示组件已加载完成，`loading` 表示启用但尚未 ready，`disabled` 表示当前配置未启用，`error` 表示启动或加载失败。`Sparse` 作为一个组件展示，`mode` 表示当前 sparse 查询方式，例如 `app`。

### 文件聚合列表

`GET /api/files`

这是前端内部管理接口。查询参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `limit` | int | 否 | `50` | 本页最多返回条数，服务端最大按 `200` 处理 |
| `cursor` | string | 否 | - | 上一页返回的 `next_cursor`，前端原样传回 |

响应示例：

```json
{
  "files": [
    {
      "id": "upstream-file-001",
      "filename": "example.pdf",
      "chunk_count": 12
    }
  ],
  "next_cursor": "MTc4NjU5NjAwMDAwMDpjOGQ1ZjJlMmZkOWE0ZWZjOTFlZmMwYWFiNmU2M2E1Zg",
  "has_more": true
}
```

### 向量数据列表

`GET /api/chunks`

这是前端数据库页使用的内部查看接口，直接列出向量库里的 chunk 数据。查询参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `limit` | int | 否 | `50` | 本页最多返回条数，服务端最大按 `200` 处理 |
| `cursor` | string | 否 | - | 上一页返回的 `next_cursor`，前端原样传回 |

响应示例：

```json
{
  "chunks": [
    {
      "id": "016d0e2f4a8f4d2b9a6f1c0b6f3c34e6",
      "file_id": "upstream-file-001",
      "s3_url": "s3://bucket/path/to/example.pdf",
      "filename": "example.pdf",
      "chunk_index": 0,
      "content": "chunk 文本..."
    }
  ],
  "next_cursor": "50",
  "has_more": true
}
```

### 删除文件

`DELETE /api/files/{file_id}`

响应示例：

```json
{
  "deleted_chunks": 12
}
```

## 配置文件

后端通过 `CONFIG_FILE` 选择配置文件，配置文件位于 `backend/config/`。

本地 native 运行默认使用 `local.yaml`。手动启动后端时可以显式指定：

```bash
CONFIG_FILE=local.yaml
```

Docker 运行使用前面的 `just deploy cpu ...` 或 `just deploy gpu ...` 命令启动。

当前配置文件：

| 文件 | 用途 | 说明 |
|---|---|---|
| `local.yaml` | native 默认入口 | 连接 `http://localhost:6333`，collection 固定为 `knowledge_chunks`，默认启用 `bge_base` dense、`bm25` sparse（`tokenizer=jieba`），不加载 rerank。 |
| `docker-cpu.yaml` | Docker CPU 入口 | 连接 Docker Compose 内的 Qdrant 服务名 `qdrant`，默认启用 `bge_base` dense、`bm25` sparse（`tokenizer=jieba`），不加载 rerank。 |
| `docker-gpu.yaml` | Docker GPU 入口 | 连接 Docker Compose 内的 Qdrant 服务名 `qdrant`，默认启用 `bge_m3` dense、`bge_m3` vector sparse、`bge_reranker_v2_m3` rerank。 |
| `qdrant-bge-base.yaml` | Qdrant 评估入口 | 固定 BGE-base dense + app BM25，collection 为 `qdrant_bge_base_knowledge_chunks`。 |
| `qdrant-bge-m3.yaml` | Qdrant 评估入口 | 固定 BGE-M3 dense + BGE-M3 vector sparse + app BM25，collection 为 `qdrant_bge_m3_knowledge_chunks`。 |
| `chroma-bge-base.yaml` | Chroma 评估入口 | 固定 BGE-base dense + app BM25，collection 为 `chroma_bge_base_knowledge_chunks`。 |
| `chroma-bge-m3.yaml` | Chroma 评估入口 | 固定 BGE-M3 dense + app BM25，collection 为 `chroma_bge_m3_knowledge_chunks`。Chroma local 不启用 vector sparse。 |
| `milvus-bge-base.yaml` | Milvus 评估入口 | 固定 BGE-base dense + app BM25，collection 为 `milvus_bge_base_knowledge_chunks`。 |
| `milvus-bge-m3.yaml` | Milvus 评估入口 | 固定 BGE-M3 dense + BGE-M3 vector sparse + app BM25，collection 为 `milvus_bge_m3_knowledge_chunks`。 |
| `milvus-builtin-bm25.yaml` | Milvus 评估入口 | 固定 BGE-base dense + Milvus BM25 vector sparse + app BM25，collection 为 `milvus_builtin_bm25_knowledge_chunks`。 |
| `milvus-lite-bge-base.yaml` | Milvus Lite 评估入口 | 固定 BGE-base dense + app BM25，collection 为 `milvus_lite_bge_base_knowledge_chunks`。 |
| `milvus-lite-bge-m3.yaml` | Milvus Lite 评估入口 | 固定 BGE-M3 dense + BGE-M3 vector sparse + app BM25，collection 为 `milvus_lite_bge_m3_knowledge_chunks`。 |
| `milvus-lite-builtin-bm25.yaml` | Milvus Lite 评估入口 | 固定 BGE-base dense + Milvus BM25 vector sparse + app BM25，collection 为 `milvus_lite_builtin_bm25_knowledge_chunks`。 |

配置文件固定会影响索引结构的内容：向量库、dense 模型、vector sparse 类型和 collection 名。`rerank`、`ocr` 可以在配置文件内用 `enable` 切换；`sparse_mode` 是查询时选择 `app` 或 `vector`，可选值由 `/api/config` 返回。

本地 native 切换配置示例：

```bash
CONFIG_FILE=milvus-bge-base.yaml .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

## Benchmark

准确性 benchmark 每个问题执行一次，按问题分别生成报告：

```bash
RUN_BENCHMARK=1 backend/.venv/bin/python -m pytest backend/tests/benchmark/test_search_accuracy_benchmark.py -m benchmark -s
```

性能 benchmark 对同一问题重复执行，输出 p50 / p95 / p99：

```bash
RUN_BENCHMARK=1 BENCHMARK_RUNS=30 backend/.venv/bin/python -m pytest backend/tests/benchmark/test_search_benchmark.py -m benchmark -s
```

## LangSmith

LangSmith 默认关闭。需要跟踪搜索链路时设置环境变量：

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=你的 LangSmith API Key
export LANGSMITH_PROJECT=rag-search
```

native 后端启动时会读取这些环境变量。Docker 启动时 compose 会把这些变量透传到 backend 容器。

搜索链路已经使用 LangChain Runnable / Retriever 组织，开启 LangSmith 后可以看到：

```text
search
  prepare_plan
  dense / sparse retriever
  fusion
  dedupe
  rerank
  format_response
```

## 日志

应用日志由配置文件里的 `logging` 控制：

```yaml
logging:
  level: INFO
  max_bytes: 10485760
  backup_count: 5
  search_trace: true
```

默认只输出 JSONL 到 stdout。需要 native 运行时同时落文件，可以加：

```yaml
logging:
  level: INFO
  file: logs/rag.jsonl
  max_bytes: 10485760
  backup_count: 5
  search_trace: true
```

Docker 运行时由 Docker `json-file` driver 按大小滚动容器 stdout 日志。

## 数据目录

本地数据目录按数据库产品分组：

```text
qdrant_data/

chroma_data/

milvus_data/
  standalone/
  lite/
    lite.db
```

Qdrant 和 Milvus Standalone 是服务型数据库，backend 通过网络访问。Chroma local 和 Milvus Lite 是嵌入式文件库，本地后端和 Docker 后端使用同一份数据目录；不要同时启动两个后端访问同一份嵌入式库文件。
