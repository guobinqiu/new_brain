# RAG Knowledge Search

## Native 启动

Native 方式只把后端和前端跑在宿主机上，默认仍使用 Docker 启动 Qdrant、MinIO 和 PostgreSQL。

准备模型：

```bash
just models all
```

1. 启动 Qdrant、MinIO 和 PostgreSQL：

```bash
docker compose -f deploy/svc/docker-compose.yml up -d qdrant minio postgres
```

2. 启动后端：

```bash
cd backend
S3_ENDPOINT_URL=http://localhost:9000 CONFIG_FILE=local.yaml .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 6000
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

Docker 部署读取 `deploy/.env`。首次部署先从模板生成本机配置：

```bash
cp deploy/.env.example deploy/.env
```

启动共享依赖：

```bash
just svc up
```

CPU 应用节点：

```bash
just rag cpu build
just rag cpu up
```

GPU 应用节点：

`deploy/.env` 中设置：

```env
CONFIG_FILE=docker-gpu.yaml
```

```bash
just rag gpu build
just rag gpu up
```

国内网络构建时可以加镜像开关：

```bash
USE_CN_MIRROR=true just rag cpu build
USE_CN_MIRROR=true just rag gpu build
```

停止：

```bash
just svc down
just rag cpu down
just rag gpu down
```

重启：

```bash
just svc restart
just rag cpu restart
just rag gpu restart
```

Docker 前端访问地址：

```text
http://<服务器地址>
```

Docker API 地址：

```text
http://<服务器地址>/api
```

多节点监控和日志：

- `/api` 由 Nginx 负载均衡到 backend 节点。
- 管理台通过 `/api/nodes/monitor` 和 `/api/nodes/config` 聚合所有节点状态。
- 日志页通过后端接口查询集中日志。
- 共享依赖只部署一套；所有 app 节点同构运行 backend、frontend、nginx 和 Promtail。
- 节点差异写在各节点 `deploy/.env`：`RAG_NODE_ID` 标识当前节点，`DATABASE_URL`、`QDRANT_URL`、`S3_ENDPOINT_URL` 和 `LOKI_URL` 指向共享依赖所在节点的 IP 或域名。

## API

上游系统真正需要调用的业务入口是索引和搜索；鉴权是调用前置步骤。完整接口说明见 [API 文档](docs/api.md)。

总览：

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/open/files` | 同步索引对象存储文件，完成后返回 `file_id` |
| `POST` | `/api/open/search` | 按 `query` 和可选 `file_ids` 搜索知识库 |
| `DELETE` | `/api/open/files/{file_id}` | 删除当前应用向量库中的索引文件 |

索引接口接收 `presigned_url`、`s3_url`、可选 `filename`、可选 `file_id` 和可选 `parser`。上游传 `file_id` 时服务端原样保存，推荐使用 UUID；不传时由 RAG 生成 UUID。`parser` 不传时使用配置文件默认解析器；`standard` 是标准解析，`fast` 是快速解析。搜索时不传 `file_ids` 表示全库搜索。

上游系统使用的 `app_id`、`access_key` 和 `secret_key` 由管理台创建。每个 `app_id` 对应独立 collection，业务接口根据 AK/SK 签名里的 `app_id` 自动选择当前应用的数据范围。索引前需要先在管理台为该 `app_id` 初始化数据库。

业务接口每次请求都带 AK/SK 签名：

请求头：

| Header | 说明 |
|---|---|
| `X-App-Id` | 调用方应用 ID |
| `X-Access-Key` | 管理台创建的 access_key |
| `X-Timestamp` | Unix 秒级时间戳 |
| `X-Signature` | HMAC-SHA256 签名 hex |

签名算法见 [API 文档](docs/api.md)。

### POST /api/open/files

同步索引对象存储文件。接口返回时，文件已经完成下载、解析、OCR、embedding 并写入向量库。

请求字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `presigned_url` | string | 是 | RAG 下载文件用的预签名 URL |
| `s3_url` | string | 是 | 稳定对象存储地址，写入 chunk metadata 用于追溯 |
| `filename` | string | 否 | 展示文件名；不传时从 `s3_url` 推导 |
| `file_id` | string | 否 | 上游指定的文件 ID，推荐使用 UUID；不传时由 RAG 生成 UUID |
| `parser` | string | 否 | `standard` / `fast`；不传使用配置文件默认值，默认 `standard` |

请求：

```json
{
  "file_id": "550e8400-e29b-41d4-a716-446655440000",
  "presigned_url": "https://example.com/presigned",
  "s3_url": "s3://bucket/path/to/example.pdf",
  "filename": "example.pdf",
  "parser": "standard"
}
```

响应：

```json
{
  "file_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### POST /api/open/search

按问题搜索知识库。`file_ids` 可省略，省略时搜索当前 `app_id` 对应 app 的整个 collection。

请求字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `query` | string | 是 | 搜索问题 |
| `mode` | string | 否 | `dense` / `sparse` / `hybrid`，不传使用服务默认值 |
| `top_k` | integer | 否 | 最多返回条数，不传使用服务默认值 |
| `fetch_k` | integer | 否 | 检索候选数量，不传使用服务默认值 |
| `rerank` | boolean | 否 | 是否启用重排，不传使用服务默认值 |
| `dense_weight` | number | 否 | hybrid 模式 dense 权重，不传使用服务默认值 |
| `sparse_weight` | number | 否 | hybrid 模式 sparse 权重，不传使用服务默认值 |
| `rrf_k` | integer | 否 | RRF 融合参数，不传使用服务默认值 |
| `file_ids` | string[] | 否 | 文件 ID 过滤；不传表示搜索当前 app 的整个 collection |

请求：

```json
{
  "query": "要查询的问题",
  "mode": "hybrid",
  "top_k": 5,
  "file_ids": ["550e8400-e29b-41d4-a716-446655440000"]
}
```

响应：

```json
{
  "results": [
    {
      "content": "命中的 chunk 文本",
      "score": 0.82,
      "file_id": "550e8400-e29b-41d4-a716-446655440000",
      "filename": "example.pdf",
      "chunk_index": 3
    }
  ],
  "mode": "hybrid",
  "rerank": true,
  "fetch_k": 20,
  "dense_weight": 0.5,
  "sparse_weight": 0.5,
  "rrf_k": 60,
  "elapsed_ms": 271.7
}
```

## 配置文件

后端通过 `CONFIG_FILE` 选择配置文件，配置文件位于 `backend/config/`。

本地 native 运行默认使用 `local.yaml`。手动启动后端时可以显式指定：

```bash
CONFIG_FILE=local.yaml
```

Docker 运行使用前面的 `just svc ...` 或 `just rag ...` 命令启动。

配置文件：

| 文件 | 用途 | 说明 |
|---|---|---|
| `local.yaml` | native 默认入口 | 连接 `http://localhost:6333`，默认启用 `bge_base` dense、`bm25` sparse（`tokenizer=jieba`），不加载 rerank。 |
| `docker-cpu.yaml` | Docker CPU 入口 | 连接 Docker Compose 内的 Qdrant 服务名 `qdrant`，默认启用 `bge_base` dense、`bm25` sparse（`tokenizer=jieba`），不加载 rerank。 |
| `docker-gpu.yaml` | Docker GPU 入口 | 连接 Docker Compose 内的 Qdrant 服务名 `qdrant`，默认启用 `bge_m3` dense、`bge_m3` sparse、`bge_reranker_v2_m3` rerank。 |
| `qdrant-bge-base.yaml` | Qdrant 评估入口 | 固定 BGE-base dense + app BM25。 |
| `qdrant-bge-m3.yaml` | Qdrant 评估入口 | 固定 BGE-M3 dense + BGE-M3 sparse。 |
| `chroma-bge-base.yaml` | Chroma 评估入口 | 固定 BGE-base dense + app BM25。 |
| `chroma-bge-m3.yaml` | Chroma 评估入口 | 固定 BGE-M3 dense + app BM25。Chroma local 不启用 vector sparse。 |
| `milvus-bge-base.yaml` | Milvus 评估入口 | 固定 BGE-base dense + app BM25。 |
| `milvus-bge-m3.yaml` | Milvus 评估入口 | 固定 BGE-M3 dense + BGE-M3 sparse。 |
| `milvus-builtin-bm25.yaml` | Milvus 评估入口 | 固定 BGE-base dense + Milvus built-in BM25 sparse。 |
| `milvus-lite-bge-base.yaml` | Milvus Lite 评估入口 | 固定 BGE-base dense + app BM25。 |
| `milvus-lite-bge-m3.yaml` | Milvus Lite 评估入口 | 固定 BGE-M3 dense + BGE-M3 sparse。 |
| `milvus-lite-builtin-bm25.yaml` | Milvus Lite 评估入口 | 固定 BGE-base dense + Milvus built-in BM25 sparse。 |

配置文件固定会影响索引结构的内容：向量库、dense 模型和 sparse 类型。collection 名由 `app_id` 生成。`rerank`、`ocr` 可以在配置文件内用 `enable` 切换；`sparse` 不做运行时切换，需要换配置文件并重建对应 collection。

本地 native 切换配置示例：

```bash
CONFIG_FILE=milvus-bge-base.yaml .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 6000
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

Docker 运行时由 Docker `json-file` driver 按大小滚动容器 stdout 日志。集中日志写入 Loki，默认保留 30 天；Docker 本地日志只做短期兜底。

## 数据目录

本地数据目录按数据库产品分组：

```text
qdrant_data/

chroma_data/

milvus_data/
  standalone/
  lite/
    lite.db

pg_data/           # PostgreSQL 文件元数据（app_files 表）
```

Qdrant 和 Milvus Standalone 是服务型数据库，backend 通过网络访问。Chroma local 和 Milvus Lite 是嵌入式文件库，本地后端和 Docker 后端使用同一份数据目录；不要同时启动两个后端访问同一份嵌入式库文件。
