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
CONFIG_FILE=local.yaml .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
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
| `POST` | `/api/upload` | 上传并索引文档 |
| `POST` | `/api/search` | 搜索知识库 |
| `GET` | `/api/documents` | 查询已索引文档列表 |
| `DELETE` | `/api/documents/{filename}` | 删除已索引文档 |

### 上传文档

`POST /api/upload`

请求类型：`multipart/form-data`

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `file` | file | 是 | - | 支持 `.pdf`、`.txt`、`.md`、`.markdown`、`.docx`、`.png`、`.jpg`、`.jpeg`、`.webp`、`.bmp` |
| `collection_type` | string | 否 | `common` | `common` 表示通用知识，`scoped` 表示范围专属知识 |
| `namespace` | string | 否 | `default` | 外部系统隔离标识；同一个外部系统的上传、搜索、列表、删除必须使用同一个值 |
| `scope_id` | string | `scoped` 时必填 | - | 范围标识 |

响应示例：

```json
{
  "filename": "example.pdf",
  "chunks": 12,
  "collection_type": "common",
  "namespace": "default",
  "scope_id": null,
  "status": "ok"
}
```

### 搜索

`POST /api/search`

请求类型：`application/json`

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `query` | string | 是 | - | 查询内容 |
| `mode` | string | 否 | 配置文件里的 `search.default_mode` | `dense`、`sparse`、`hybrid` |
| `top_k` | int | 否 | 配置文件里的 `search.top_k` | 最多返回条数，范围 `1..50` |
| `rerank` | bool | 否 | 当前配置是否启用 rerank 组件 | 是否启用重排 |
| `fetch_k` | int | 否 | 配置文件里的 `search.fetch_k` | 重排候选池，必须大于等于 `top_k` |
| `dense_weight` | number | 否 | 配置文件里的 `search.dense_weight` | 本次 hybrid 查询的 dense 权重 |
| `sparse_weight` | number | 否 | 配置文件里的 `search.sparse_weight` | 本次 hybrid 查询的 sparse 权重 |
| `rrf_k` | int | 否 | 配置文件里的 `search.rrf_k` | 本次 hybrid 查询的 RRF 参数 |
| `namespace` | string | 否 | `default` | 外部系统隔离标识；只搜索同一 `namespace` 下的数据 |
| `scope_ids` | string[] | 否 | `[]` | 范围标识列表；为空时只查通用知识，非空时同时查通用知识和范围专属知识 |

请求示例：

```json
{
  "query": "有多少华为卡",
  "mode": "hybrid",
  "top_k": 5,
  "rerank": true,
  "fetch_k": 50,
  "dense_weight": 0.5,
  "sparse_weight": 0.5,
  "rrf_k": 60,
  "namespace": "default",
  "scope_ids": []
}
```

响应字段：

| 字段 | 说明 |
|---|---|
| `results` | 搜索结果列表 |
| `mode` | 本次搜索模式 |
| `rerank` | 本次是否启用重排 |
| `fetch_k` | 本次候选池大小 |
| `dense_weight` | 本次 hybrid 查询的 dense 权重 |
| `sparse_weight` | 本次 hybrid 查询的 sparse 权重 |
| `rrf_k` | 本次 hybrid 查询的 RRF 参数 |
| `elapsed_ms` | 后端搜索耗时，单位毫秒 |

### 文档列表

`GET /api/documents`

查询参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `collection_type` | string | 否 | `all` | `all`、`common`、`scoped` |
| `namespace` | string | 否 | `default` | 外部系统隔离标识；只列出同一 `namespace` 下的文档 |
| `scope_ids` | string[] | 否 | `[]` | 范围标识列表 |

### 删除文档

`DELETE /api/documents/{filename}`

查询参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `collection_type` | string | 是 | - | `common` 或 `scoped` |
| `namespace` | string | 否 | `default` | 外部系统隔离标识；只删除同一 `namespace` 下的文档 |
| `scope_id` | string | 否 | - | 删除 scoped 文档时用于限定范围 |

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
| `local.yaml` | native 默认入口 | 连接 `http://localhost:6333`，collection 固定为 `knowledge_common` / `knowledge_scoped`，默认启用 `bge_base` dense、`bm25` sparse（`tokenizer=jieba`），不加载 rerank。 |
| `docker-cpu.yaml` | Docker CPU 入口 | 连接 Docker Compose 内的 Qdrant 服务名 `qdrant`，默认启用 `bge_base` dense、`bm25` sparse（`tokenizer=jieba`），不加载 rerank。 |
| `docker-gpu.yaml` | Docker GPU 入口 | 连接 Docker Compose 内的 Qdrant 服务名 `qdrant`，默认启用 `bge_m3` dense、`bm25` sparse（`tokenizer=jieba`）、`bge_reranker_v2_m3` rerank。 |
| `qdrant.yaml` | Qdrant 评估入口 | collection 使用 `qdrant_` 前缀。 |
| `chroma.yaml` | Chroma 评估入口 | collection 使用 `chroma_` 前缀，本地数据目录是 `chroma_data`。 |
| `milvus.yaml` | Milvus 评估入口 | collection 使用 `milvus_` 前缀。默认连接 Standalone；保留 Milvus Lite 配置但默认禁用。 |

本地 native 临时切换配置示例：

```bash
CONFIG_FILE=milvus.yaml .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
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
  common / scoped parallel
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
