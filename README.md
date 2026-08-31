# RAG Knowledge Search

## Native 启动

Native 方式只把后端和前端跑在宿主机上，默认仍使用 Docker 启动 Qdrant、MinIO 和 PostgreSQL。

准备模型：

```bash
just models all
```

1. 启动 Qdrant、MinIO 和 PostgreSQL：

```bash
just svc up
```

2. 启动 RAG 后端：

```bash
S3_ENDPOINT_URL=http://localhost:9000 CONFIG_FILE=local.yaml rag/.venv/bin/python -m uvicorn rag.main:app --host 0.0.0.0 --port 6000
```

3. 启动 LLM 后端：

```bash
OPENAI_API_KEY=dummy OPENAI_BASE_URL=http://19.16.1.233:8000/v1 MODEL_NAME=vllm DATABASE_URL=postgresql://rag:rag@localhost:5432/rag RAG_BASE_URL=http://localhost:6000 llm/.venv/bin/python -m uvicorn llm.src.main:app --host 0.0.0.0 --port 6001
```

4. 启动前端：

```bash
cd webui
npm install
npm run dev -- --host 0.0.0.0 --port 5173
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

`svc` 只包含 PostgreSQL、Qdrant、MinIO、Loki 和 Promtail，不启动 nginx。

单独启停服务：

```bash
just postgres up
just qdrant up
just minio up
just loki up
just promtail up
just nginx up
```

CPU 应用节点：

```bash
just rag build cpu
just rag up cpu
```

GPU 应用节点：

`deploy/.env` 中设置：

```env
CONFIG_FILE=docker-gpu.yaml
```

```bash
just rag build gpu
just rag up gpu
```

国内网络构建时可以加镜像开关：

```bash
USE_CN_MIRROR=true just rag build cpu
USE_CN_MIRROR=true just rag build gpu
```

停止：

```bash
just svc down
just rag down
just llm down
just webui down
just nginx down
```

重启：

```bash
just svc restart
just rag restart
just llm restart
just webui restart
just nginx restart
```

## API

上游系统真正需要调用的业务入口是索引和搜索；鉴权是调用前置步骤。完整接口说明见 [API 文档](docs/api.md)。

总览：

| 方法     | 路径                        | 说明                                       |
| -------- | --------------------------- | ------------------------------------------ |
| `POST`   | `/api/open/files`           | 同步索引对象存储文件，完成后返回 `file_id` |
| `POST`   | `/api/open/search`          | 按 `query` 和可选 `file_ids` 搜索知识库    |
| `POST`   | `/api/open/llm/chat/stream` | 流式 RAG 问答                              |
| `DELETE` | `/api/open/files/{file_id}` | 删除当前应用向量库中的索引文件             |

索引接口接收 `presigned_url`、`s3_url`、可选 `filename` 和可选 `file_id`。上游传 `file_id` 时服务端原样保存，推荐使用 UUID；不传时由 RAG 生成 UUID。搜索时不传 `file_ids` 表示全库搜索。

上游系统使用的 `app_id`、`access_key` 和 `secret_key` 由管理台创建。每个 `app_id` 对应独立 collection，业务接口根据 AK/SK 签名里的 `app_id` 自动选择当前应用的数据范围。索引前需要先在管理台为该 `app_id` 初始化数据库。

业务接口每次请求都带 AK/SK 签名：

请求头：

| Header         | 说明                    |
| -------------- | ----------------------- |
| `X-App-Id`     | 调用方应用 ID           |
| `X-Access-Key` | 管理台创建的 access_key |
| `X-Timestamp`  | Unix 秒级时间戳         |
| `X-Signature`  | HMAC-SHA256 签名 hex    |

签名算法见 [API 文档](docs/api.md)。

### POST /api/open/files

同步索引对象存储文件。接口返回时，文件已经完成下载、解析、embedding 并写入向量库。

请求字段：

| 字段            | 类型   | 必填 | 说明                                                     |
| --------------- | ------ | ---- | -------------------------------------------------------- |
| `presigned_url` | string | 是   | RAG 下载文件用的预签名 URL                               |
| `s3_url`        | string | 是   | 稳定对象存储地址，写入 chunk metadata 用于追溯           |
| `filename`      | string | 否   | 展示文件名；不传时从 `s3_url` 推导                       |
| `file_id`       | string | 否   | 上游指定的文件 ID，推荐使用 UUID；不传时由 RAG 生成 UUID |

请求：

```json
{
  "file_id": "550e8400-e29b-41d4-a716-446655440000",
  "presigned_url": "https://example.com/presigned",
  "s3_url": "s3://bucket/path/to/example.pdf",
  "filename": "example.pdf"
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

| 字段            | 类型     | 必填 | 说明                                                 |
| --------------- | -------- | ---- | ---------------------------------------------------- |
| `query`         | string   | 是   | 搜索问题                                             |
| `mode`          | string   | 否   | `dense` / `sparse` / `hybrid`，不传使用服务默认值    |
| `top_k`         | integer  | 否   | 最多返回条数，不传使用服务默认值                     |
| `fetch_k`       | integer  | 否   | 检索候选数量，不传使用服务默认值                     |
| `rerank`        | boolean  | 否   | 是否启用重排，不传使用服务默认值                     |
| `dense_weight`  | number   | 否   | hybrid 模式 dense 权重，不传使用服务默认值           |
| `sparse_weight` | number   | 否   | hybrid 模式 sparse 权重，不传使用服务默认值          |
| `rrf_k`         | integer  | 否   | RRF 融合参数，不传使用服务默认值                     |
| `file_ids`      | string[] | 否   | 文件 ID 过滤；不传表示搜索当前 app 的整个 collection |

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
      "id": "chunk-text-1",
      "content": "合同约定项目验收周期为 30 天，逾期需要提交延期说明。",
      "score": 0.91
    },
    {
      "id": "chunk-table-1",
      "content": "| 项目 | 金额 | 备注 |\n|---|---:|---|\n| 设备费 | 120000 | 首期 |\n| 服务费 | 30000 | 年费 |",
      "score": 0.86
    },
    {
      "id": "chunk-text-2",
      "content": "付款条件为验收通过后 10 个工作日内支付尾款。",
      "score": 0.79
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
