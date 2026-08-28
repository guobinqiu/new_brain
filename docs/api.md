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

删除当前应用数据库，同时清理该应用的文件记录。

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
POST /api/open/files
Content-Type: application/json
```

认证使用 AK/SK 请求签名（请求头与签名算法见开头「鉴权」一节），认证失败返回 401。

请求字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `presigned_url` | string | 是 | - | 本次索引用的一次性下载 URL，不保存到索引 |
| `s3_url` | string | 是 | - | 稳定对象存储地址，例如 `s3://bucket/key`，写入 metadata 用于追溯 |
| `filename` | string | 否 | 从 `s3_url` 推导 | 自定义展示文件名 |
| `file_id` | string | 否 | RAG 生成 | 上游文件 ID；传入时原样保存，推荐使用 UUID |
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
  "file_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

同步索引成功返回表示文件已经完成下载、解析、embedding 并写入向量库。

错误码：

| 状态码 | 场景 |
|---|---|
| 400 | 不支持的文件类型（以 `filename` 或 object key 的扩展名判断）；未传 `filename` 且 `s3_url` 不含 object key，无法推导文件名；解析器不可用 |
| 401 | AK/SK 签名认证失败：缺签名头、access key 无效、时间戳偏差超过 300 秒、签名不匹配 |
| 403 | 请求体 `app_id` 与签名 `X-App-Id` 不一致（`app_id is not allowed`） |
| 409 | 目标 app 数据库未初始化（`app database is not initialized`） |
| 422 | 请求体校验失败：缺 `presigned_url`/`s3_url`、`s3_url` 不以 `s3://` 开头、`file_id` 不是 UUID 或长度不在 1..64、包含未定义字段 |
| 429 | 请求过于频繁，超过 `api.rate_limit_index` |
| 500 | 下载或索引处理失败（如 `presigned_url` 失效、文件解析异常） |
| 503 | 应用未完成初始化（`search is not initialized`） |

### 创建异步索引任务

```http
POST /api/open/files/jobs
Content-Type: application/json
```

认证使用 AK/SK 请求签名（请求头与签名算法见开头「鉴权」一节）。签名验证通过后主体类型为 `app`，绑定 `X-App-Id` 对应的应用；缺签名头、access key 无效、时间戳偏差超过 300 秒或签名不匹配返回 401。

请求字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `presigned_url` | string | 是 | - | 本次索引用的一次性下载 URL（上游用自己的凭据对自己的 MinIO/S3 生成），只在下载时使用，不保存到索引 |
| `s3_url` | string | 是 | - | 稳定对象存储地址，例如 `s3://bucket/key`，写入 metadata 用于追溯；必须以 `s3://` 开头并包含 bucket 和 object key |
| `filename` | string | 否 | 从 `s3_url` 推导 | 展示文件名，扩展名以此字段（缺省时取 object key）判断；对象 key 无扩展名时必须传带受支持扩展名的 `filename`，否则返回 400 |
| `file_id` | string | 否 | 服务端生成 | 上游文件 ID；传入时原样保存，推荐使用 UUID |
| `app_id` | string | 否 | 签名里的 `X-App-Id` | AK/SK 主体已绑定单一应用，通常不传；传入时必须与签名应用一致，否则返回 403 |

请求示例：

```json
{
  "file_id": "550e8400-e29b-41d4-a716-446655440000",
  "presigned_url": "https://upstream.example.com/presigned?X-Amz-Signature=...",
  "s3_url": "s3://bucket/path/to/example.pdf",
  "app_id": "tenant_a"
}
```

响应 202：

```json
{
  "file_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

错误码：

| 状态码 | 场景 |
|---|---|
| 400 | 不支持的文件类型（以 `filename` 或 object key 的扩展名判断）；未传 `filename` 且 `s3_url` 不含 object key，无法推导文件名；解析器不可用 |
| 401 | AK/SK 签名认证失败：缺签名头、access key 无效、时间戳偏差超过 300 秒、签名不匹配 |
| 403 | 请求体 `app_id` 与签名 `X-App-Id` 不一致（`app_id is not allowed`） |
| 409 | 目标 app 数据库未初始化（`app database is not initialized`） |
| 422 | 请求体校验失败：缺 `presigned_url`/`s3_url`、`s3_url` 不以 `s3://` 开头、`file_id` 不是 UUID 或长度不在 1..64、包含未定义字段 |
| 429 | 进程内待处理任务队列已满 |
| 503 | 应用未完成初始化（`search is not initialized`） |

异步索引入队成功返回 202 和 `file_id`。下载、解析、embedding 和向量库写入由 backend 进程内的索引消费器后台执行。没有任务状态查询接口；调用方可以用 `file_id` 通过搜索接口验证索引是否就绪。`presigned_url` 的有效性在后台消费时才校验，入队成功不代表下载成功。进程内待处理任务队列已满时返回 429。任务不落盘，backend 重启会丢失队列中未完成的任务，需要重新提交索引。

管理台内部版本 `POST /api/files/jobs` 见下文：认证改用 User JWT，`file_id` 和 `app_id` 必填。

### 创建异步索引任务（管理台内部）

```http
POST /api/files/jobs
Content-Type: application/json
```

`POST /api/open/files/jobs` 的管理台内部版本，两侧共用 `_create_index_job()` 实现，业务行为完全相同：异步入队、成功返回 202 和 `{file_id}`、队列满返回 429。差异只在认证方式和请求模型。

认证使用 User JWT（`Authorization: Bearer <access_token>`，登录接口签发），不走 AK/SK 签名。

请求字段与 `POST /api/open/files` 相同，但 `file_id` 必填：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `presigned_url` | string | 是 | - | 本次索引用的一次性下载 URL，管理台链路通常由 `/api/presign` 对 `/api/upload` 返回的 `s3_url` 生成 |
| `s3_url` | string | 是 | - | 稳定对象存储地址，写入 metadata 用于追溯 |
| `filename` | string | 否 | 从 `s3_url` 推导 | 自定义展示文件名 |
| `file_id` | string | 是 | - | `/api/upload` 返回的文件 ID；RAG 生成的值为 UUID |
| `app_id` | string | 是 | - | 管理台当前选择的应用 ID（User JWT 不绑定业务 app） |

`file_id` 必填的原因：`/api/upload` 上传成功时已经把返回的 `file_id` 写进 MinIO 对象路径 `uploads/{app_id}/{file_id}/{filename}`，后续的索引、删除和文件列表都以这一前缀互相对齐。创建任务时如果不传 `file_id`，服务器会另外生成一个新的 `file_id`，向量库记录将与上传对象、文件列表断链：删除接口删不掉 MinIO 里的原文，文件列表也会出现一条无法对齐的幽灵记录。

响应：

```json
{
  "file_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

错误码：

| 状态码 | 场景 |
|---|---|
| 401 | User JWT 缺失或无效 |
| 400 | 不支持的文件类型；User JWT 未传 `app_id`（`app_id is required`） |
| 409 | 目标 app 数据库未初始化（`app database is not initialized`） |
| 422 | 请求体校验失败：缺 `file_id` 或其他必填字段、`file_id` 不是 UUID、`s3_url` 不以 `s3://` 开头等 |
| 429 | 进程内待处理任务队列已满 |
| 503 | 应用未完成初始化（`search is not initialized`） |

任务同样不落盘，backend 重启会丢失队列中未完成的任务，需要重新提交索引。

open 侧（外部上游）的 `file_id` 保持可选：外部文件不经过 `/api/upload`，没有对象路径对齐需求，缺省时由服务端生成新的 `file_id`。

## 搜索

```http
POST /api/open/search
Content-Type: application/json
```

超过 `api.rate_limit` 时返回 429。

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
  "fetch_k": 20,
  "dense_weight": 0.5,
  "sparse_weight": 0.5,
  "rrf_k": 60,
  "file_ids": ["550e8400-e29b-41d4-a716-446655440000"]
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

`results` 元素字段：

| 字段 | 说明 |
|---|---|
| `id` | chunk ID |
| `content` | 命中的 chunk 文本 |
| `score` | 相关性分数 |

响应示例：

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

## 本地对象存储辅助

### 上传文件到对象存储

```http
POST /api/upload
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | file | 是 | 支持 `.pdf`、`.txt`、`.md`、`.docx`、`.xlsx`、`.png`、`.jpg`、`.jpeg`、`.webp`、`.bmp` |
| `app_id` | string | 是 | 当前管理台选择的应用 |

响应：

```json
{
  "file_id": "550e8400-e29b-41d4-a716-446655440000",
  "s3_url": "s3://rag/uploads/imsdom/550e8400-e29b-41d4-a716-446655440000/example.pdf",
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
  "presigned_url": "http://minio:9000/rag/uploads/example.pdf?..."
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
| `components` | 运行组件列表，包括 Store、Dense、Sparse、Rerank、OCR 的状态和绑定模型 |
| `capabilities` | 服务能力，包括搜索模式、是否支持配置写入和重启 |
| `index_contract` | 索引与存储诊断信息，包括 collection、dense 和 sparse 配置等 |

`/api/monitor` 是轻量状态接口，不读取向量 chunk，不统计文件数或 chunk 数。

### 运行日志与搜索 Trace

```http
GET /api/logs
GET /api/traces
```

运行日志和搜索 Trace 由后端统一按时间范围查询。管理台使用 User JWT 访问后端接口。

常用查询参数：

| 参数 | 说明 |
|---|---|
| `start` | 开始时间，支持毫秒时间戳、纳秒时间戳或 ISO 时间 |
| `end` | 结束时间，支持毫秒时间戳、纳秒时间戳或 ISO 时间 |
| `limit` | 返回条数上限 |
| `node_id` | 日志查询可选，按节点过滤 |
| `container` | 日志查询可选，按容器过滤 |
| `app_id` | Trace 查询可选，按应用过滤 |

响应里的 `has_more` 表示当前时间范围内可能还有更早记录；`next_end` 是下一批查询的结束时间，继续查询时把它作为 `end` 传回即可。

### 上传文件列表

```http
GET /api/files?limit=50&cursor=...&app_id=<app_id>
```

列出当前 app 的索引文件。数据来自 PostgreSQL `app_files` 表（database 组件维护的文件元数据），软删除的文件不再出现。返回的 `id` 是 `file_id`，`s3_url` 指向 MinIO 对象，key 固定为 `uploads/{app_id}/{file_id}/{filename}`。

分页参数：

- `cursor`：数字主键 id（响应中的 `next_cursor` 原样回传即可）。
- `limit`：默认 50，上限 200。
- `total`：当前 app 未软删文件总数，不是当前页条数。

状态字段：

- `queued`：已入队，等待索引。
- `indexing`：正在索引。
- `success`：索引成功。
- `failed`：索引失败，错误原因见 `error`。

响应：

```json
{
  "files": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "filename": "example.pdf",
      "s3_url": "s3://rag/uploads/imsdom/550e8400-e29b-41d4-a716-446655440000/example.pdf",
      "size": 1024,
      "chunk_count": 12,
      "status": "success",
      "error": null,
      "created_at": "2026-08-18T17:00:00+08:00",
      "indexed_at": "2026-08-18T17:00:30+08:00"
    }
  ],
  "next_cursor": null,
  "has_more": false,
  "total": 1
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
  "file_ids": ["550e8400-e29b-41d4-a716-446655440000"]
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
