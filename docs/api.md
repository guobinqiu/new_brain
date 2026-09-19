# API 文档

本文列出后端 HTTP 接口。外部系统集成通常只需要鉴权、索引和搜索接口；管理、日志和本地对象存储辅助接口用于运维和管理台。

公开业务路径为 `/api/v1/rag/*` 和 `/api/v1/llm/*`，RAG 管理接口保持 `/api/rag/*`，集群管理接口为 `/api/ops/*`。旧业务路径不提供兼容别名。

## 健康检查与网关

RAG 使用根路径 `GET /health` 检查存活、`GET /ready` 检查就绪，均不要求业务鉴权，也不带版本或业务前缀。网关 `http://localhost:5175/health` 和 `http://localhost:5175/ready` 精确转发到 RAG；RAG 的 `/ready` 会检查 Parser、Inference、向量库和已启用的关系数据库；部署中的 RAG 探针直接请求 `http://127.0.0.1:6000/ready`。Parser、Inference 的 `/health`、`/ready` 和 LLM 的 `/health` 可直接访问各自服务端口。没有带业务前缀的健康检查兼容别名。

Parser 服务接口为 `/v1/parse/file`，Inference 保持 `/v1/*`。现有内部网关入口剥离 `/api/internal/parser` 或 `/api/internal/inference` 前缀后转发，例如 `/api/internal/parser/v1/parse/file` 转发为 `/v1/parse/file`，`/api/internal/inference/v1/embeddings` 转发为 `/v1/embeddings`，保留查询参数。

## 鉴权

外部系统调用业务接口时，每个请求都使用 Bearer API key。

关系数据库启用时，App Key 从数据库校验；全部关闭时，从 `rag.yaml` 的 `auth.apps` 列表读取应用绑定校验。关库前须将现有数据库应用绑定的 `app_id` 和 `api_key` 原样填入 `auth.apps`，关库后沿用凭据，调用方无需更换 Key。两种来源不会同时使用，数据库故障不回退到配置凭据

请求头：

| Header | 说明 |
|---|---|
| `Authorization` | `Bearer <api_key>` |

管理台接口使用 User JWT，`/api/rag/*` 和 `/api/ops/*` 复用同一个登录 token：

```http
Authorization: Bearer <access_token>
```

### 管理台登录

```http
POST /api/rag/login
Content-Type: application/json
```

请求：

```json
{
  "username": "admin",
  "password": "<RAG_ADMIN_PASSWORD>"
}
```

响应：

```json
{
  "access_token": "...",
  "token_type": "Bearer"
}
```

管理员用户名读取 `rag.yaml` 的 `auth.admin.username`，密码读取 `deploy/.env` 的 `RAG_ADMIN_PASSWORD`

配置响应中的数据库 `url` 是脱敏后的 PostgreSQL 连接串，密码等敏感字段显示为 `***`，不是可直接复用的认证信息

## 集群管理

集群管理接口只给管理台使用。Ops 服务通过 Docker Engine API 访问 Swarm manager 管理 service、task、node 和日志，通过 Docker CLI 执行 `docker stack deploy`。固定一台发布 manager 维护 `deploy/.env`、`deploy/ctrl.yaml`、`deploy/infra.yaml`、`deploy/deploy.yaml`、代码目录和挂载路径；Ops 必须部署在这台发布 manager 上，才能保证部署文件中的宿主机绑定路径正确

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/ops/services` | 查看 Swarm service 列表 |
| `POST` | `/api/ops/services/{service}/start` | 将 service scale 到 1 |
| `POST` | `/api/ops/services/{service}/stop` | 将 service scale 到 0 |
| `POST` | `/api/ops/services/scale` | 将应用 service 调整为指定副本数 |
| `POST` | `/api/ops/services/{service}/rollout` | 对 service 执行滚动更新 |
| `GET` | `/api/ops/services/{service}/tasks` | 查看 service tasks |
| `GET` | `/api/ops/services/{service}/logs` | 查看 service 日志 |
| `GET` | `/api/ops/nodes` | 查看 Swarm 节点 |
| `GET` | `/api/ops/swarm/join-command?role=worker` | 获取节点加入命令 |
| `GET` | `/api/ops/configs` | 查看可编辑配置列表 |
| `GET` | `/api/ops/configs/{name}` | 读取配置文件 |
| `POST` | `/api/ops/configs/{name}/validate` | 校验配置内容 |
| `PUT` | `/api/ops/configs/{name}` | 保存配置 |
| `POST` | `/api/ops/configs/apply` | 应用配置；服务配置滚动更新对应 service，部署配置发布对应 stack |
| `POST` | `/api/ops/stack/deploy?target=app` | 发布应用；`target=infra` 仅发布基础服务，省略时默认为 app |
| `POST` | `/api/ops/stack/remove?target=app` | 删除选定 stack；支持 app/infra，不删除绑定目录数据和外部网络 |

`/api/ops/services/scale` 请求体为 `{"service":"brain_inference","replicas":3}`，仅用于标记 `group=app` 的服务。所有 service 参数使用 Swarm 的实际服务名。`configs/{name}` 支持 `rag`、`parser`、`inference`、`llm`、`env`、`deploy`、`infra`。保存配置只写文件；`POST /api/ops/configs/apply` 请求体为 `{"name":"inference"}`，服务配置会 rollout 对应 service，`deploy` 和 `env` 发布应用 stack，`infra` 发布基础服务 stack。

`target=app` 使用 `deploy/deploy.yaml` 和 `STACK`（默认 `brain`）；`target=infra` 使用 `deploy/infra.yaml` 和 `INFRA_STACK`（默认 `brain_infra`）。两者共用 `deploy/.env`，修改其中的基础服务变量后需单独发布 infra；发布 app 不会更新 infra。未知 target 返回 422。旧的合并部署迁移步骤见 README。

## 应用管理

应用管理接口只给管理台使用。外部系统不调用这些接口。

### 创建应用

```http
POST /api/rag/apps
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
  "api_key": "..."
}
```

有库模式下 `api_key` 保存在 PostgreSQL，外部业务系统用它调用 `/api/v1/rag/*` 和 `/api/v1/llm/*` 接口。无库模式应用绑定由部署配置维护，动态创建和删除应用返回 503，应用列表只读

### 查询应用列表

```http
GET /api/rag/apps
```

响应：

```json
{
  "apps": [
    {
      "app_id": "tenant_a",
      "api_key": "..."
    }
  ]
}
```

### 删除应用

```http
DELETE /api/rag/apps/{app_id}
```

删除应用的 API key 记录，不删除向量库 collection。删除索引数据使用应用数据库删除接口。

### 初始化应用数据库

```http
POST /api/rag/apps/{app_id}/database
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
GET /api/rag/apps/{app_id}/database
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
DELETE /api/rag/apps/{app_id}/database
```

删除当前应用对应的向量库 collection。

响应：

```json
{
  "app_id": "tenant_a",
  "deleted": true
}
```

## 索引

### 管理台人工重试

失败文件继续使用 `POST /api/rag/files`，请求体只提交已有记录的标识：

```json
{"app_id":"imsdom","file_id":"550e8400-e29b-41d4-a716-446655440000"}
```

后端读取该应用下的失败记录，通过 `apps.presign_config` 获取新的下载 URL，再用原 `file_id` 执行完整索引流程。仅 `failed` 记录可执行，重复点击或非失败状态返回 409；同一次操作的成功、失败响应保持五个顶层字段。获取下载地址失败也写回文件的 `error`，文件保持 `failed`。该功能需要 PostgreSQL，无库模式返回 503；没有后台自动重试任务

### 下载地址请求配置

`apps.presign_config` 为 TEXT，保存 Jinja2 模板。新建应用时自动读取 `services/rag/config/presign.jinja`，将 `YOUR_APP_API_KEY` 替换为新应用的实际 API key，与应用记录一起保存。默认调用内部 presign API，应用页面可直接编辑配置，无需导入。修改模板文件影响之后创建的应用，不覆盖已有应用的配置；模板中的接口 URL 需保证 RAG 进程可以访问

```http
GET /api/rag/apps/{app_id}/presign-config
PUT /api/rag/apps/{app_id}/presign-config
```

两个接口使用管理台 JWT。GET 返回 `{"presign_config":"模板文本"}`；PUT 使用 `Content-Type: text/plain`，请求体直接提交模板文本，保存后下一次操作生效

```jinja2
{
  "url": "http://127.0.0.1:6000/api/v1/rag/presign",
  "method": "POST",
  "headers": {
    "Content-Type": "application/json",
    "Authorization": "Bearer YOUR_APP_API_KEY"
  },
  "params": {},
  "body": {"s3_url": {{ s3_url | tojson }}},
  "response_url_path": "presigned_url"
}
```

可用变量为 `app_id`、`file_id`、`s3_url`、`filename`，来自失败记录及所属应用。`tojson` 自动处理字符串引号和转义，模板渲染后通过 `json.loads()` 解析。`params` 编码为 URL 查询参数，`body` 根据 `Content-Type` 编码为 JSON 或 `application/x-www-form-urlencoded` 表单，其他 Content-Type 使用字符串请求体。GET 可以只配 `params`，POST 可以同时配 `params` 和 `body`

上游响应按 `response_url_path` 取值，如 `data.download_url`，数组下标可写成 `data.0.url`，空路径表示整个 JSON 响应就是 URL 字符串。提取结果必须为 HTTP(S) 下载 URL。API key 可放在 headers 或参数中；供应商 AK/SK 动态签名需要接入其签名实现，当前模板不会自行计算签名。请求超时由 `storage.presign_timeout` 控制，受索引剩余预算约束

有库模式要求目标 app 已经初始化向量集合，未初始化时返回 `app database is not initialized`。无库模式会在首次索引时创建当前已鉴权应用的集合，不需要关系数据库或管理台初始化
外部系统的 `app_id` 来自 Bearer API key，请求体里不用传 `app_id`。User JWT 面向管理台，不绑定业务 app；管理台调用索引、搜索、文件列表或向量数据接口时需要显式传 `app_id`。

### 同步索引对象存储文件

```http
POST /api/v1/rag/files
Content-Type: application/json
```

公开接口 `/api/v1/rag/files` 使用 Bearer API key，`app_id` 来自 API key，请求体里不用传 `app_id`。
管理台接口 `/api/rag/files` 使用 User JWT，需要在请求体里传 `app_id`。

请求字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `presigned_url` | string | 否 | - | 本次索引用的一次性下载 URL，不保存到索引；不传时通过当前 app 的预签名配置生成 |
| `s3_url` | string | 是 | - | 稳定对象存储地址，例如 `s3://bucket/key`，写入 metadata 用于追溯 |
| `filename` | string | 否 | 从 `s3_url` 推导 | 自定义展示文件名 |
| `file_id` | string | 否 | RAG 生成 | 上游文件 ID；传入时原样保存，推荐使用 UUID |
| `app_id` | string | User JWT 必填，API key 调用不传 | - | 管理台选择的应用 ID |

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
  "success": true,
  "error": null,
  "service": null,
  "retryable": false,
  "traceId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "file_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

同步索引成功返回表示文件已经完成下载、解析、embedding、向量写入和旧分片清理；启用 PG 时还包括文件成功状态更新

### 批量同步索引对象存储文件

```http
POST /api/v1/rag/files/batch
Content-Type: application/json
```

批量接口只负责把多个文件拆成多个单文件索引请求，并通过 RAG service 地址反调 `/api/v1/rag/files`，使 Swarm 多副本可以参与处理。每个文件必须传稳定 `file_id`。

请求字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `files` | object[] | 是 | - | 待索引文件数组，最多 `api.batch_index.max_files` 个，默认 10 |
| `files[].file_id` | string | 是 | - | 上游稳定文件 ID，最长 64 字符 |
| `files[].presigned_url` | string | 否 | - | 本次索引用的一次性下载 URL；不传时通过当前 app 的预签名配置生成 |
| `files[].s3_url` | string | 是 | - | 稳定对象存储地址，例如 `s3://bucket/key` |
| `files[].filename` | string | 否 | 从 `s3_url` 推导 | 自定义展示文件名 |
| `max_concurrency` | int | 否 | `api.batch_index.max_concurrency` | 本次请求并发数，不能超过配置上限，默认上限 5 |

请求示例：

```json
{
  "files": [
    {
      "file_id": "file-a",
      "presigned_url": "https://example.com/a",
      "s3_url": "s3://bucket/path/a.pdf",
      "filename": "a.pdf"
    },
    {
      "file_id": "file-b",
      "presigned_url": "https://example.com/b",
      "s3_url": "s3://bucket/path/b.docx",
      "filename": "b.docx"
    }
  ],
  "max_concurrency": 5
}
```

响应：

```json
{
  "success": false,
  "files": [
    {
      "success": true,
      "error": null,
      "service": null,
      "retryable": false,
      "traceId": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "file_id": "file-a"
    },
    {
      "success": false,
      "error": "parser unavailable",
      "service": "parser",
      "retryable": true,
      "traceId": "cccccccccccccccccccccccccccccccc",
      "file_id": "file-b"
    }
  ]
}
```

批量请求完成分发和汇总后返回 200；`success` 表示本次批量中是否全部成功；单个文件的成功、失败和是否可重试以 `files[]` 内的结果为准。参数校验、鉴权、限流等批量入口自身失败仍返回对应 4xx。

进入索引处理后的错误统一返回以下 JSON，不包含内部阶段和写入状态：

```json
{
  "success": false,
  "error": "fieldName(sparse_vector) not found",
  "service": "vector",
  "retryable": false,
  "traceId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "file_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

两个索引入口的参数校验、鉴权、限流错误也使用此结构。进入业务函数后保留请求的 file_id 或生成新 ID；入口提前拒绝时生成本次失败的 file_id，不创建文件记录。其他 RAG API 的成功响应格式不变

RAG、Parser、Inference、LLM 的未捕获异常返回 HTTP 500，正文包含 `success: false`、原始 `error`、`service`、`retryable: false` 和 `traceId`；路径包含 `file_id` 时一并返回。完整堆栈只写日志，不使用固定的“Internal Server Error”替代异常说明。外部错误缺少可识别的说明字段时保留响应正文，前端按文本显示，不执行其中的 HTML。LLM 流式响应开始后的错误通过 SSE 错误事件返回。

索引成功、失败响应均包含相同的六个顶层字段：`success`、`error`、`service`、`retryable`、`traceId`、`file_id`，不使用 `data` 或 `detail` 包装，也不使用自定义错误码。成功时 `error`、`service` 为 null、`retryable` 为 false；失败时 `error` 保留原始错误说明，没有说明时为 null。完整异常堆栈写入日志。retryable 表示当前错误是否适合由调用方继续重试，不代表本次请求没有产生部分写入。向量库和 PG 未分类的写入错误默认 false

服务内只在失败发生的局部阶段做快速重试：Parser 重试方舟 PDF 解析调用；Inference 重试当前 provider 的 embedding、sparse embedding 和 rerank 调用；RAG 重试 PostgreSQL metadata 写入和 Milvus/Qdrant 集合创建、upsert、flush、stale chunk 清理等向量库写入。RAG 不重跑整条索引链路，向量库写入重试不会重新解析或重新 embedding。`max_attempts` 包含第一次正常执行，默认 3；`interval_seconds` 是固定等待时间，默认 0.5 秒。当前 PyMilvus 3.0.1 仍有无法通过公开开关彻底关闭的 schema 刷新重试。上游从首次提交起建议提供稳定的 `file_id`，重试复用同一个 ID 和相同文档；同一应用同一文件需串行提交。`file_id` 可省略，但连接中断时上游可能拿不到服务端生成的 ID

向量写入成功后 PG 更新失败，接口返回失败但不删除向量。错误响应不代表回滚；写入超时可能已提交。相同 ID 重试最终成功后覆盖分片并更新 PG，不提供跨副本并发事务保证

`rag.yaml` 的 `api.index_timeout` 默认 600 秒，从工作线程开始执行索引时计时，Nginx 等待固定 900 秒。索引入口同步执行，阶段间检查截止时间，超出预算返回 HTTP 504，后续阶段不再启动；正在执行的同步调用需等待结束或自身超时，不保证恰好到 600 秒返回，不能把超时当作撤销操作。上游和其他代理的等待时间需要大于应用预算并留出余量

`service` 标识错误所属服务或组件，如 `rag`、`parser`、`inference`、`vector`、`database`、`presign`。内部调用保留下游返回的 service；连接下游失败时标记目标服务。旧错误记录没有 service 时返回 null。LLM 的 SSE 错误事件使用 `{type: "error", message, service, trace_id}`，模型调用超时时 service 为 `llm`。

每个阶段日志包含耗时和 `trace_id`，上游通过响应的 `traceId` 关联排查。内部服务解析并透传 traceparent；外部服务暂不发送该头，调用日志仍关联当前 TraceId

错误码：

| 状态码 | 场景 |
|---|---|
| 400 | 不支持的文件类型（以 `filename` 或 object key 的扩展名判断）；未传 `filename` 且 `s3_url` 不含 object key，无法推导文件名 |
| 401 | Bearer API key 认证失败：缺认证头、格式错误或 api key 无效 |
| 403 | 请求体 `app_id` 与 API key 对应应用不一致（`app_id is not allowed`） |
| 409 | 目标 app 数据库未初始化（`app database is not initialized`） |
| 422 | 请求体校验失败：缺 `s3_url`、`s3_url` 不以 `s3://` 开头、`file_id` 长度不在 1..64、包含未定义字段 |
| 429 | 请求过于频繁，超过 `api.rate_limit_index` |
| 500 | 向量 SDK、PG 或其他内部处理失败 |
| 502 | 外部服务拒绝、计费异常或返回不合法数据 |
| 503 | 应用未就绪、外部服务断连或限流 |
| 504 | 单次调用超时或整次索引超时 |

## 搜索

```http
POST /api/v1/rag/search
Content-Type: application/json
```

超过 `api.rate_limit` 时返回 429。

请求字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `query` | string | 是 | - | 查询内容 |
| `mode` | string | 否 | 配置文件里的 `search.mode` | `dense`、`sparse` 或 `hybrid`；`hybrid` 在 sparse 不可用时自动降级为 `dense` |
| `top_k` | int | 否 | 配置文件里的 `search.top_k` | 最多返回条数，范围 `1..50` |
| `rerank` | bool | 否 | 配置文件里的 `search.rerank` | 是否启用 rerank |
| `rerank_fetch_k` | int | 否 | 配置文件里的 `search.rerank_fetch_k` | rerank 前召回数量，范围 `1..100`，传 `top_k` 时必须大于等于 `top_k` |
| `rrf_k` | int | 否 | 配置文件里的 `search.rrf_k` | hybrid 模式下 RRF 融合参数，范围 `1..1000` |
| `file_ids` | string[] | 否 | - | 限定搜索范围；不传表示全库搜索；空数组会被拒绝；最多 1000 个 |

请求示例：

```json
{
  "query": "有多少华为卡",
  "mode": "hybrid",
  "top_k": 5,
  "rerank": false,
  "rerank_fetch_k": 20,
  "rrf_k": 60,
  "file_ids": ["550e8400-e29b-41d4-a716-446655440000"]
}
```

响应字段：

| 字段 | 说明 |
|---|---|
| `results` | 搜索结果列表 |
| `mode` | 本次搜索模式 |
| `rerank` | 本次是否启用 rerank |
| `rerank_fetch_k` | rerank 启用时的召回数量；未启用时为 `null` |
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
  "mode": "dense",
  "rerank": false,
  "rerank_fetch_k": null,
  "elapsed_ms": 271.7
}
```

## 本地对象存储辅助

### 上传文件到对象存储

```http
POST /api/rag/upload
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | file | 是 | 支持 `.pdf`、`.txt`、`.md`、`.doc`、`.docx`、`.xls`、`.xlsx`、`.ppt`、`.pptx` |
| `app_id` | string | 是 | 当前管理台选择的应用 |
| `file_id` | string | 否 | 不传为新增；传入则上传当前应用已有文件的新版本，需要 PostgreSQL 文件记录，排队或索引中的文件返回 409 |

上传仅供管理后台使用，通过 User JWT 鉴权。更新上传复用原 `file_id`，对象保存到 `uploads/{app_id}/{file_id}/{version}/{filename}`，不覆盖旧文件。上传本身不修改文件记录；随后调用索引接口，传返回的 `file_id`、`filename`、`s3_url` 和新预签名 URL，才更新原记录并重建索引。新版索引失败后，原记录的人工重试使用新版地址。此流程不是跨对象存储、向量库和 PG 的原子事务。

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
POST /api/rag/presign
Content-Type: application/json
```

另提供 `POST /api/v1/rag/presign`，请求和响应相同，使用应用 Bearer API key，只允许为当前应用的 `uploads/{app_id}/` 对象生成下载地址，可作为上述模板的请求目标

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

### 运行日志与搜索 Trace

```http
GET /api/rag/logs
GET /api/rag/traces
```

运行日志和搜索 Trace 由后端统一按时间范围查询，返回普通 JSON，不提供 SSE `/stream` 端点。管理台使用 User JWT 访问后端接口，网关通过 `/api/rag/` 转发。

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

### 索引文件列表

```http
GET /api/rag/files?limit=50&cursor=...&app_id=<app_id>
```

列出当前 app 的索引文件。数据来自关系数据库中的文件记录，返回的 `id` 是 `file_id`，`s3_url` 是索引时记录的来源地址。无关系数据库时此接口返回 503，不通过向量库拼造文件状态记录

分页参数：

- `cursor`：数字主键 id（响应中的 `next_cursor` 原样回传即可）。
- `limit`：默认 50，上限 200。
- `total`：当前 app 未软删文件总数，不是当前页条数。

状态字段：

- `success`：索引成功。
- `failed`：索引失败，`error` 返回 `{error, service, retryable, traceId}` 或 null。PG 的原有 error TEXT 字段保存同一 JSON，无表结构变更；重启恢复的旧任务没有原请求 TraceId 时存 null，旧的非 JSON 错误记录不直接展示。重新索引和索引成功会清除 error

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
      "service": null,
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
POST /api/rag/chunks
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

### 查看向量本体

```http
GET /api/rag/apps/{app_id}/chunks/{chunk_id}/dense-vector
```

管理台按行查看当前 chunk 在向量库里的向量本体。列表接口不默认返回向量本体，避免分页响应过大。

`dense-vector` 返回 dense embedding 数组。

### 删除索引文件

```http
DELETE /api/rag/files/{file_id}
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
DELETE /api/v1/rag/files/{file_id}
```

上游接口只删除当前 app 向量库里的 chunks，不删除对象存储中的原始文件。

## Parser API

```http
POST /v1/parse/file
Content-Type: application/json
Authorization: Bearer <SERVICE_API_KEY>
```

请求 JSON：`{"presigned_url": "https://storage.example/report.pdf?signature=...", "filename": "report.pdf"}`。两个字段必填，下载地址必须使用 HTTP 或 HTTPS。

返回按阅读顺序排列的 `blocks`，不在 Parser 中切片。Parser 下载文件时返回 `file_size`（字节数）；云端直接读取 URL 时省略该字段。

PDF 后端由 `parser.yaml` 的 enable 开关选择。`mineru_cloud` 直接提交 URL 到单文件解析接口，轮询任务并转换结果 JSON；URL 必须能被云平台访问，内网 MinIO 地址不能直接给云平台使用。旧 Office（`.doc/.xls/.ppt`）需要启用 `mineru_cloud`。本地 MinerU、火山方舟及原生格式解析由 Parser 下载到临时目录后处理，结束或异常时清理。RAG 只转交 URL 和文件名，不下载或转上传文件内容。

`parser.download_timeout` 控制本地解析前的下载超时，单位秒。MinerU 云端通过 `MINERU_API_KEY` 读取 Token，`mineru_cloud.timeout` 控制提交、轮询及读取结果的总时间。启用 `mineru_cloud` 时关闭其他 PDF 后端的 enable。

`mineru` 为本地 MinerU 4.0 Python SDK 后端，下载 PDF 后解析全文，返回相同的 blocks；`tier` 支持 `flash/basic/standard/advanced`，`parse_method` 支持 `auto/ocr/txt`。模型准备见 `scripts/download_models.txt`，与其他 PDF 后端只能启用一个，不需要云端 API Key。

TXT 按空行分段，Word 按原生段落读取，Markdown 按语法元素读取，PPT 按页内文本元素读取并携带幻灯片页码，Excel 按表格结构输出。所有格式的文本块统一带 `kind`，不为不存在的类别生成空块

RAG 根据 `kind` 和 `chunk_size` 组合相邻文本：标题开启章节，连续标题跟随后正文，正文和列表项按顺序组合，超长文本再拆分，不跨章节、页码、表格或公式合并正文。TXT 保留空行段落边界。代码块不拆分，长度允许时与相邻说明组合；表格保留 caption 和完整 rows，同页紧邻且未跟随正文的 heading 与表格同片，相同 caption 不重复，不拼接普通前后文；单个代码块和表格可以超过普通文本的 chunk_size 限制

```json
{
  "blocks": [
    {"type": "text", "kind": "heading", "text": "向量数据库对比", "page": 1},
    {
      "type": "table",
      "rows": [["向量库", "稠密检索"], ["Milvus", "支持"], ["Qdrant", "支持"]],
      "caption": "检索能力对比",
      "page": 1
    },
    {"type": "formula", "text": "E = mc^2", "format": "latex", "page": 2},
    {"type": "text", "kind": "paragraph", "text": "没有页码的段落"}
  ]
}
```

| type | 必填字段 | 可选字段 |
| --- | --- | --- |
| `text` | `text`、`kind` | `page` |
| `table` | `rows`，每行一个数组，每个单元格一个字符串 | `caption`、`page` |
| `formula` | `text`、`format` | `page` |

页码从 1 开始，没有页码时省略 `page`；没有表格标题时省略 `caption`，不返回空字符串或 `null`

`kind` 为 `heading` 标题、`paragraph` 段落、`list_item` 列表项、`code` 代码块、`text` 无法明确分类的文本。TXT 段落使用 `paragraph`；PDF 使用解析后端的分类信息，无法识别时使用 `text`

所有解析后端及文件类型使用同一响应结构，不返回 `role`、`level`、`header`、`footer`、`html` 或图片块。表格不返回 `text`，由 RAG 将紧邻 heading、`caption` 和完整 `rows` 按上述规则组合为一个 Markdown 分片

## Inference API

Inference 通过 `inference.yaml` 选择模型提供方，配置 dense、sparse 和 rerank 模型

| provider | dense 内部调用 | sparse 内部调用 | rerank 内部调用 |
| --- | --- | --- | --- |
| `embedded` | `HuggingFaceDense.embed_documents()` / `HuggingFaceDense.embed_query()` | `BgeM3Sparse.embed_documents()` / `BgeM3Sparse.embed_query()` | `CrossEncoderRerank.rerank()` |
| `tei` | `POST {dense.base_url}/v1/embeddings` | 无 | `POST {rerank.base_url}/rerank` |
| `vllm` | `POST {dense.base_url}/v1/embeddings` | 无 | `POST {rerank.base_url}/v1/rerank` |
| `siliconflow-cn` | `POST {base_url}/embeddings` | 无 | `POST {base_url}/rerank` |
| `siliconflow-intl` | `POST {base_url}/embeddings` | 无 | `POST {base_url}/rerank` |
| `volcengine` | `POST {base_url}/embeddings/multimodal` | `POST {base_url}/embeddings/multimodal` | `POST {rerank_base_url}/api/knowledge/service/rerank` |

| 接口 | 请求字段 | 响应 |
| --- | --- | --- |
| `GET /v1/models` | 无 | 当前 dense 模型和维度，sparse、rerank 模型；未启用时为 null |
| `POST /v1/embeddings` | `input`：非空字符串或非空文本数组 | dense 向量 `data` 数组 |
| `POST /v1/sparse_embeddings` | `input`：非空字符串或非空文本数组 | sparse 向量 `data` 数组 |
| `POST /v1/rerank` | `query`、`documents`、`top_k` | `results` 数组，每项包含 `index`、`document`、`relevance_score` |
| `GET /ready` | 无 | 就绪状态及 `dense`、`sparse`、`rerank` 能力 |

`/v1/models` 和三个 POST 接口使用 `Authorization: Bearer <INFERENCE_API_KEY>`，部署时映射为服务内的 SERVICE_API_KEY。请求中的可选 `model` 不切换服务端模型，实际模型由 inference 配置决定

模型规格响应示例：

```json
{
  "dense": {"model_name": "doubao-embedding-vision-251215", "dimensions": 1024},
  "sparse": {"model_name": "doubao-embedding-vision-251215"},
  "rerank": null
}
```

`/v1/models` 返回当前模型规格。本地模型复用加载时确定的维度；外部模型已配置维度时直接读取，没有已知维度时首次探测并缓存。规格获取失败返回错误，不缓存失败结果

两个向量接口都接受 `{"input":["文本一","文本二"]}` 或 `{"input":"文本"}`。向量类型由 dense、sparse 路径区分，无需额外类型字段。字符串调用模型的 embed_query 方法，数组调用 embed_documents 方法；响应按输入顺序返回，每段文本对应一个向量

dense 响应项包含 `object: "embedding"`、`embedding`、`index`；sparse 响应项包含 `object: "sparse_embedding"`、`indices`、`values`、`index`。外层统一为 `{"object":"list","data":[...],"model":null}`，model 回填请求值。仅提供表中接口，不保留旧路径兼容入口；重排仍使用 `/v1/rerank`

```json
{
  "status": "ready",
  "capabilities": {"dense": true, "sparse": false, "rerank": true}
}
```

`/ready` 返回当前就绪状态和已启用能力，不触发推理。修改配置后重启 Inference 生效。硅基流动适配仅提供 dense 与可选 rerank

失败响应平铺返回 `error`、`service`、`retryable`、`traceId`。`error` 保存原始错误说明，没有时为 null；完整异常堆栈写入日志。例如计费异常返回 HTTP 502：

```json
{
  "error": "balance is insufficient",
  "service": "inference",
  "retryable": false,
  "traceId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}
```

达到配置的 `max_attempts` 后仍失败时，返回最后一次错误
- 网络异常、超时和 HTTP 5xx 按临时错误处理
- HTTP 4xx 按不可重试错误处理
- 无效响应为 false

依据：[SiliconFlow embeddings](https://docs.siliconflow.cn/docs/api/embeddings-post)、[rerank](https://docs.siliconflow.cn/docs/api/rerank-post)、[方舟错误码表](https://www.volcengine.com/docs/82379/1299023)
