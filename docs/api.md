# API 文档

本文列出后端 HTTP 接口。外部系统集成通常只需要鉴权、索引和搜索接口；管理、监控、日志和本地对象存储辅助接口用于运维和管理台。

## 鉴权

所有业务接口使用：

```http
Authorization: Bearer <access_token>
```

### 换取 JWT

```http
POST /api/auth/token
Content-Type: application/json
```

外部系统使用 `client_credentials`：

```json
{"grant_type":"client_credentials"}
```

请求头：

| Header | 说明 |
|---|---|
| `X-App-Id` | 调用方应用 ID |
| `X-Access-Key` | 配置里的 `access_key` |
| `X-Timestamp` | Unix 秒级时间戳 |
| `X-Signature` | HMAC-SHA256 签名 hex |

AK/SK 签名算法：

1. `body` 是本次 HTTP 请求实际发送的原始 body 字节。
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

响应：

```json
{
  "access_token": "...",
  "token_type": "Bearer"
}
```

管理用户使用 `password`：

```json
{
  "grant_type": "password",
  "username": "admin",
  "password": "admin123"
}
```

## 索引

### 同步索引对象存储文件

```http
POST /api/index
Content-Type: application/json
```

请求字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `presigned_url` | string | 是 | - | 本次索引用的一次性下载 URL，不保存到索引 |
| `s3_url` | string | 是 | - | 稳定对象存储地址，例如 `s3://bucket/key`，写入 metadata 用于追溯 |
| `filename` | string | 否 | 从 `s3_url` 推导 | 自定义展示文件名 |

请求示例：

```json
{
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
POST /api/index/jobs
Content-Type: application/json
```

请求字段与 `POST /api/index` 相同。

响应：

```json
{
  "job_id": "a3f47d1b05a944d4927e0c87531f9c2a"
}
```

异步索引只创建任务。下载、解析、OCR、embedding 和向量库写入由后台 worker 执行。

### 查询异步索引任务

```http
GET /api/index/jobs/{job_id}
```

响应：

```json
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
```

`status` 常见取值：`queued`、`started`、`finished`、`failed`、`not_found`。`job_id` 只用于查询索引任务状态；`finished` 后，上游需要在自己的文件表或映射表里保存响应里的 `file_id`，后续搜索指定文件范围时传回该值；`failed` 时读取 `error`。

### 查询异步索引任务列表

```http
GET /api/index/jobs?limit=50&cursor=0
```

响应：

```json
{
  "jobs": [],
  "next_cursor": null,
  "has_more": false
}
```

## 搜索

```http
POST /api/search
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

响应：

```json
{
  "s3_url": "s3://rag-dev/uploads/550e8400e29b41d4a716446655440000/example.pdf",
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
GET /api/traces?limit=50&cursor=...
```

返回最近搜索请求的链路耗时。

### 运行日志

```http
GET /api/logs
```

返回 `text/event-stream`。连接建立后先输出最近日志 ring buffer，再持续输出实时运行日志。

### 文件聚合列表

```http
GET /api/files?limit=50&cursor=...
```

从向量库 chunk metadata 聚合文件级信息。

### 向量数据列表

```http
GET /api/chunks?limit=50&cursor=...&file_ids=<file_id>,<file_id>
```

直接分页查看向量库里的 chunk 数据。`file_ids` 不传时查看全库 chunk。

### 删除文件

```http
DELETE /api/files/{file_id}
```

响应：

```json
{
  "deleted_chunks": 12
}
```
