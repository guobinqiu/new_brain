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

上游系统真正需要调用的业务入口是索引和搜索；鉴权是调用前置步骤。完整接口说明见 [API 文档](docs/api.md)。

鉴权前置：

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/auth/token` | 外部系统 access_key/secret_key 换取 Service JWT |

同步接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/index` | 同步索引对象存储文件，完成后返回 `file_id` |

异步接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/index/jobs` | 创建异步索引任务，返回 `job_id` |
| `GET` | `/api/index/jobs/{job_id}` | 查询异步索引任务状态，完成后返回 `file_id` |

查询接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/search` | 按 `query` 和可选 `file_ids` 搜索知识库 |

上游如果已经有自己的队列、限流和重试机制，可以调用同步索引；否则建议调用异步索引并轮询任务状态。异步索引完成后，上游需要在自己的文件表或映射表里保存 `file_id`，后续搜索指定文件范围时传回该值。索引接口接收 `presigned_url`、`s3_url` 和可选 `filename`，`file_id` 由 RAG 生成。搜索时不传 `file_ids` 表示全库搜索。

## 配置文件

后端通过 `CONFIG_FILE` 选择配置文件，配置文件位于 `backend/config/`。

本地 native 运行默认使用 `local.yaml`。手动启动后端时可以显式指定：

```bash
CONFIG_FILE=local.yaml
```

Docker 运行使用前面的 `just deploy cpu ...` 或 `just deploy gpu ...` 命令启动。

配置文件：

| 文件 | 用途 | 说明 |
|---|---|---|
| `local.yaml` | native 默认入口 | 连接 `http://localhost:6333`，collection 固定为 `knowledge_chunks`，默认启用 `bge_base` dense、`bm25` sparse（`tokenizer=jieba`），不加载 rerank。 |
| `docker-cpu.yaml` | Docker CPU 入口 | 连接 Docker Compose 内的 Qdrant 服务名 `qdrant`，默认启用 `bge_base` dense、`bm25` sparse（`tokenizer=jieba`），不加载 rerank。 |
| `docker-gpu.yaml` | Docker GPU 入口 | 连接 Docker Compose 内的 Qdrant 服务名 `qdrant`，默认启用 `bge_m3` dense、`bge_m3` sparse、`bge_reranker_v2_m3` rerank。 |
| `qdrant-bge-base.yaml` | Qdrant 评估入口 | 固定 BGE-base dense + app BM25，collection 为 `qdrant_bge_base_knowledge_chunks`。 |
| `qdrant-bge-m3.yaml` | Qdrant 评估入口 | 固定 BGE-M3 dense + BGE-M3 sparse，collection 为 `qdrant_bge_m3_knowledge_chunks`。 |
| `chroma-bge-base.yaml` | Chroma 评估入口 | 固定 BGE-base dense + app BM25，collection 为 `chroma_bge_base_knowledge_chunks`。 |
| `chroma-bge-m3.yaml` | Chroma 评估入口 | 固定 BGE-M3 dense + app BM25，collection 为 `chroma_bge_m3_knowledge_chunks`。Chroma local 不启用 vector sparse。 |
| `milvus-bge-base.yaml` | Milvus 评估入口 | 固定 BGE-base dense + app BM25，collection 为 `milvus_bge_base_knowledge_chunks`。 |
| `milvus-bge-m3.yaml` | Milvus 评估入口 | 固定 BGE-M3 dense + BGE-M3 sparse，collection 为 `milvus_bge_m3_knowledge_chunks`。 |
| `milvus-builtin-bm25.yaml` | Milvus 评估入口 | 固定 BGE-base dense + Milvus built-in BM25 sparse，collection 为 `milvus_builtin_bm25_knowledge_chunks`。 |
| `milvus-lite-bge-base.yaml` | Milvus Lite 评估入口 | 固定 BGE-base dense + app BM25，collection 为 `milvus_lite_bge_base_knowledge_chunks`。 |
| `milvus-lite-bge-m3.yaml` | Milvus Lite 评估入口 | 固定 BGE-M3 dense + BGE-M3 sparse，collection 为 `milvus_lite_bge_m3_knowledge_chunks`。 |
| `milvus-lite-builtin-bm25.yaml` | Milvus Lite 评估入口 | 固定 BGE-base dense + Milvus built-in BM25 sparse，collection 为 `milvus_lite_builtin_bm25_knowledge_chunks`。 |

配置文件固定会影响索引结构的内容：向量库、dense 模型、sparse 类型和 collection 名。`rerank`、`ocr` 可以在配置文件内用 `enable` 切换；`sparse` 不做运行时切换，需要换配置文件并重建对应 collection。

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
