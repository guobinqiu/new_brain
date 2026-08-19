# API 文档

本文列出后端 HTTP 接口。外部系统集成通常只需要鉴权、索引和搜索接口；管理、监控、日志和本地对象存储辅助接口用于运维和管理台。

## 鉴权

外部系统调用业务接口时，每个请求都使用 AK/SK 签名。

请求头：

| Header | 说明 |
|---|---|
| `X-App-Id` | 调用方应用 ID |
| `X-Access-Key` | 管理台创建的 `access_key` |
| `X-Timestamp` | Unix 秒级时间戳 |
| `X-Signature` | HMAC-SHA256 签名 hex |

AK/SK 签名算法：

1. `body` 是本次 HTTP 请求实际发送的原始 body 字节；没有 body 时使用空字节。
2. `BODY_SHA256 = sha256(body).hexdigest()`。
3. `METHOD` 使用大写 HTTP 方法。
4. `PATH` 只使用 URL path，不包含 query string。
5. `TIMESTAMP` 使用 `X-Timestamp` 的原始字符串。
6. `APP_ID` 使用 `X-App-Id` 的原始字符串。
7. `string_to_sign` 按下面顺序用 `\n` 拼接，末尾不额外追加换行：

```text
METHOD
PATH
TIMESTAMP
BODY_SHA256
APP_ID
```

8. `signature = hmac_sha256(secret_key, string_to_sign).hexdigest()`。
9. 服务端用常量时间比较校验 `X-Signature` 和计算出的 `signature`。
10. 服务端校验 `X-Timestamp` 和服务器当前时间差不能超过 300 秒。

管理台接口使用 User JWT：

```http
Authorization: Bearer <access_token>
```

### 管理台登录

```http
POST /api/login
Content-Type: application/json
```

请求：

```json
{
  "username": "admin",
  "password": "admin123"
}
```

响应：

```json
{
  "access_token": "...",
  "token_type": "Bearer"
}
```

## 应用管理

应用管理接口只给管理台使用。外部系统不调用这些接口。

### 创建应用

```http
POST /api/apps
Content-Type: application/json
```

请求：

```json
{
  "app_id": "tenant_a"
}
```

响应：

```json
{
  "app_id": "tenant_a",
  "access_key": "...",
  "secret_key": "..."
}
```

创建应用只生成 AK/SK，不创建或删除向量库数据。

### 查询应用列表

```http
GET /api/apps
```

响应：

```json
{
  "apps": [
    {
      "app_id": "tenant_a",
      "access_key": "...",
      "secret_key": "..."
    }
  ]
}
```

### 删除应用凭证

```http
DELETE /api/apps/{app_id}
```

只删除该应用的 AK/SK，不删除向量库数据。

响应：

```json
{
  "deleted": true
}
```

### 初始化应用数据库

```http
POST /api/apps/{app_id}/database
```

初始化该应用对应的 chunks collection。重复调用是幂等操作。

响应：

```json
{
  "app_id": "tenant_a",
  "initialized": true
}
```

### 查询应用数据库状态

```http
GET /api/apps/{app_id}/database
```

响应：

```json
{
  "app_id": "tenant_a",
  "exists": true,
  "chunk_count": 0,
  "empty": true
}
```

### 删除应用数据库

```http
DELETE /api/apps/{app_id}/database
```

只允许删除空数据库。数据库内已有 chunk 时返回 `app database is not empty`。

响应：

```json
{
  "app_id": "tenant_a",
  "deleted": true
}
```

## 索引

索引接口要求目标 app 已经初始化数据库；未初始化时返回 `app database is not initialized`。
外部系统的 `app_id` 来自 AK/SK 签名，请求体里不用传 `app_id`。User JWT 面向管理台，不绑定业务 app；管理台调用索引、搜索、文件列表或向量数据接口时需要显式传 `app_id`。

### 同步索引对象存储文件

```http
POST /api/open/index
Content-Type: application/json
```

请求字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `presigned_url` | string | 是 | - | 本次索引用的一次性下载 URL，不保存到索引 |
| `s3_url` | string | 是 | - | 稳定对象存储地址，例如 `s3://bucket/key`，写入 metadata 用于追溯 |
| `filename` | string | 否 | 从 `s3_url` 推导 | 自定义展示文件名 |
| `file_id` | string | 否 | RAG 生成 | 上游文件 ID；传入时必须是 UUID，后端统一保存为 32 位 hex |
| `app_id` | string | User JWT 必填，AK/SK 调用不传 | - | 管理台选择的应用 ID |

请求示例：

```json
{
  "file_id": "550e8400-e29b-41d4-a716-446655440000",
  "presigned_url": "https://example.com/presigned",
  "s3_url": "s3://bucket/path/to/example.pdf"
}
```

响应：

```json
{
  "file_id": "550e8400e29b41d4a716446655440000"
}
```

同步索引成功返回表示文件已经完成下载、解析、OCR、embedding 并写入向量库。

### 创建异步索引任务

```http
POST /api/open/index/jobs
Content-Type: application/json
```

请求字段与 `POST /api/open/index` 相同。管理台使用 User JWT 调用 `POST /api/index/jobs` 创建任务时必须传 `file_id`，也就是 `/api/upload` 返回的文件 ID。

响应：

```json
{
  "job_id": "a3f47d1b05a944d4927e0c87531f9c2a"
}
```

异步索引只创建任务。下载、解析、OCR、embedding 和向量库写入由后台 worker 执行。

### 查询异步索引任务

```http
POST /api/open/index/jobs/status
Content-Type: application/json
```

请求：

```json
{
  "job_ids": ["a3f47d1b05a944d4927e0c87531f9c2a"]
}
```

响应：

```json
{
  "jobs": [
    {
      "file_id": "550e8400e29b41d4a716446655440000",
      "job_id": "a3f47d1b05a944d4927e0c87531f9c2a",
      "status": "finished",
      "filename": "example.pdf",
      "s3_url": "s3://bucket/path/to/example.pdf",
      "chunk_count": 12,
      "error": null,
      "created_at": "2026-08-17T09:00:00+08:00",
      "enqueued_at": "2026-08-17T09:00:00+08:00",
      "started_at": "2026-08-17T09:00:02+08:00",
      "ended_at": "2026-08-17T09:00:18+08:00"
    }
  ]
}
```

`queued` / `started` 表示任务已接受或正在处理。

`finished` 表示索引已写入向量库，响应里包含 `file_id`。

`failed` 表示索引失败，响应里包含 `error`。

`not_found` 表示任务不存在或状态已过期。

## 搜索

```http
POST /api/open/search
Content-Type: application/json
```

请求字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `query` | string | 是 | - | 查询内容 |
| `mode` | string | 否 | 配置文件里的 `search.default_mode` | `dense`、`sparse`、`hybrid` |
| `top_k` | int | 否 | 配置文件里的 `search.top_k` | 最多返回条数，范围 `1..50` |
| `rerank` | bool | 否 | 配置是否启用 rerank 组件 | 是否启用重排 |
| `fetch_k` | int | 否 | 配置文件里的 `search.fetch_k` | 重排候选池，必须大于等于 `top_k` |
| `dense_weight` | number | 否 | 配置文件里的 `search.dense_weight` | hybrid 查询的 dense 权重 |
| `sparse_weight` | number | 否 | 配置文件里的 `search.sparse_weight` | hybrid 查询的 sparse 权重 |
| `rrf_k` | int | 否 | 配置文件里的 `search.rrf_k` | hybrid 查询的 RRF 参数 |
| `file_ids` | string[] | 否 | - | 限定搜索范围；不传表示全库搜索；空数组会被拒绝；最多 1000 个 |

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
  "file_ids": ["550e8400e29b41d4a716446655440000"]
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

## 本地对象存储辅助

### 上传文件到对象存储

```http
POST /api/upload
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | file | 是 | 支持 `.pdf`、`.txt`、`.md`、`.markdown`、`.docx`、`.png`、`.jpg`、`.jpeg`、`.webp`、`.bmp` |
| `app_id` | string | 是 | 当前管理台选择的应用 |

响应：

```json
{
  "file_id": "550e8400e29b41d4a716446655440000",
  "s3_url": "s3://rag-dev/uploads/imsdom/550e8400e29b41d4a716446655440000/example.pdf",
  "filename": "example.pdf"
}
```

### 生成短期下载地址

```http
POST /api/presign
Content-Type: application/json
```

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `s3_url` | string | 是 | - | 稳定对象存储地址 |
| `expires_in` | int | 否 | `3600` | 签名有效期，单位秒，范围 `60..86400` |

响应：

```json
{
  "presigned_url": "http://minio:9000/rag-dev/uploads/example.pdf?..."
}
```

## 管理与诊断

### 运行监控

```http
GET /api/monitor
```

响应字段：

| 字段 | 说明 |
|---|---|
| `ready` | 应用是否完成初始化 |
| `profile` | 运行 profile，包括配置名和 store 概要 |
| `components` | 运行组件列表，包括 Store、Redis、Dense、Sparse、Rerank、OCR 的状态和绑定模型 |
| `capabilities` | 服务能力，包括搜索模式、是否支持配置写入和重启 |
| `index_contract` | 索引与存储诊断信息，包括 collection、dense 和 sparse 配置等 |

`/api/monitor` 是轻量状态接口，不读取向量 chunk，不统计文件数或 chunk 数。

### 搜索 Trace

```http
GET /api/traces?limit=200
```

返回最近搜索请求的链路耗时。后端只保留最近 200 条内存 trace，接口不用于长期历史查询。

### 运行日志

```http
GET /api/logs/stream
```

返回 `text/event-stream`。连接建立后先输出最近日志 ring buffer，再持续输出实时运行日志。

### 索引任务列表

```http
GET /api/index/jobs?limit=200&app_id=<app_id>
```

管理台任务列表接口，User JWT 鉴权。`app_id` 传入时按该应用过滤；`limit` 默认 50，必须大于 0，上限 200。接口返回最近 `limit` 条任务快照，没有 cursor 分页，不用于全量历史查询。

响应：

```json
{
  "jobs": [
    {
      "app_id": "imsdom",
      "file_id": "550e8400e29b41d4a716446655440000",
      "job_id": "a3f47d1b05a944d4927e0c87531f9c2a",
      "status": "finished",
      "filename": "example.pdf",
      "s3_url": "s3://bucket/path/to/example.pdf",
      "chunk_count": 12,
      "error": null,
      "created_at": "2026-08-17T09:00:00+08:00",
      "enqueued_at": "2026-08-17T09:00:00+08:00",
      "started_at": "2026-08-17T09:00:02+08:00",
      "ended_at": "2026-08-17T09:00:18+08:00"
    }
  ]
}
```

任务列表用于管理台展示最近任务快照；任务详情和状态语义见"查询异步索引任务"。

### 索引任务事件流

```http
GET /api/index/jobs/stream?app_id=<app_id>
```

管理台实时任务事件接口，User JWT 鉴权，`app_id` 必填。返回 `text/event-stream`。任务开始、成功或失败时，worker 通过 Redis Pub/Sub 发布事件，API 进程订阅并转发为 SSE 帧：

```text
data: {"app_id": "imsdom", "job_id": "a3f47d1b05a944d4927e0c87531f9c2a", "status": "started", "filename": "example.pdf"}
```

事件字段：

| 字段 | 说明 |
|---|---|
| `app_id` | 应用 ID |
| `job_id` | 任务 ID |
| `status` | `started` / `finished` / `failed`；worker 重试的中间状态不发事件 |
| `filename` | 展示文件名，可能为 `null` |

事件发布失败（Redis 不可用）时索引流程不受影响，管理台通过索引任务列表接口轮询兜底。

### 上传文件列表

```http
GET /api/files?limit=50&cursor=...&app_id=<app_id>
```

从 MinIO/S3 按当前 app 前缀分页列出原始上传文件。返回的 `id` 是 `file_id`，MinIO key 固定为 `uploads/{app_id}/{file_id}/{filename}`。

响应：

```json
{
  "files": [
    {
      "id": "550e8400e29b41d4a716446655440000",
      "filename": "example.pdf",
      "s3_url": "s3://rag-dev/uploads/imsdom/550e8400e29b41d4a716446655440000/example.pdf",
      "size": 1024,
      "created_at": "2026-08-18T17:00:00+08:00"
    }
  ],
  "next_cursor": null,
  "has_more": false
}
```

### 向量数据列表

```http
POST /api/chunks
```

请求：

```json
{
  "limit": 50,
  "cursor": null,
  "app_id": "imsdom",
  "file_ids": ["550e8400e29b41d4a716446655440000"]
}
```

直接分页查看向量库里的 chunk 数据。`file_ids` 不传时查看全库 chunk。

### 删除索引文件

```http
DELETE /api/files/{file_id}
```

管理台删除文件会同时删除当前 app 向量库里的 chunks，以及 MinIO/S3 中 `uploads/{app_id}/{file_id}/` 前缀下的原始上传对象。

响应：

```json
{
  "deleted_chunks": 12
}
```

上游系统删除索引文件：

```http
DELETE /api/open/files/{file_id}
```

上游接口只删除当前 app 向量库里的 chunks，不删除对象存储中的原始文件。
