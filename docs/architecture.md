# 知识检索后端架构

本文说明知识检索后端的目标架构。系统以文件为父对象，以 chunk 为检索对象，外部系统通过 `file_id` 限定搜索范围。

架构目标是：向量库、dense 模型、sparse 检索、rerank 模型都通过 yaml profile 声明。服务入口和搜索流程只依赖稳定能力接口，不把某个模型、向量库或部署环境写死到业务逻辑里。

---

## 1. 架构目标

- 外部契约保持稳定，调用方不需要知道底层使用哪种向量库或模型。
- 向量库可通过 Store profile 切换。
- dense 能力可通过 Dense profile 切换。
- sparse 能力可通过 Sparse profile 切换。
- rerank 能力可通过 Rerank profile 切换。
- 每个外部系统使用独立 chunks collection，collection 名由 `app_id` 统一生成。
- 支持通过多个 `file_id` 限定搜索范围。
- 支持 dense、sparse、hybrid 检索模式。
- 支持可选 rerank。
- 启动时通过配置文件决定使用哪套组合。
- 应用层统一鉴权：管理用户使用 User JWT；外部系统业务请求直接使用 AK/SK HMAC 签名。
- 代码和配置使用通用命名，不绑定具体业务。

---

## 2. 核心概念

| 概念      | 含义                                                                 |
| --------- | -------------------------------------------------------------------- |
| `file_id` | 文件主键，外部系统保存后用于限定搜索范围                             |
| file      | 上传或对象存储索引的文件父对象，文件级信息从 chunk metadata 聚合得到 |
| chunk     | 文件切片后的检索对象，存储在向量库 collection                        |
| `top_k`   | 最多返回条数                                                         |
| `fetch_k` | rerank 候选池大小，只在 `rerank=true` 时使用                         |
| dense     | 语义向量检索                                                         |
| sparse    | 关键词、词权重或稀疏向量检索                                         |
| hybrid    | dense 和 sparse 的融合检索                                           |
| User JWT  | 管理用户登录后得到的 JWT，用于管理功能                               |
| `app_id`  | 外部系统身份标识，用于鉴权、审计和 collection 隔离                   |

查询范围示例：

```json
{
  "file_ids": ["<file_id>"]
}
```

`file_ids` 不传时搜索当前应用的整个 collection；传空数组会被拒绝；一次最多允许 1000 个 `file_id`。`file_id` 在当前应用的 collection 内使用；上游可以传入 UUID 作为 `file_id`，不传时由 RAG 生成。

### 2.1 总体架构图

```mermaid
flowchart LR
  Client["外部系统 / 管理入口"] --> Auth["Auth: User JWT 或 AK/SK 签名"]
  Auth --> Entry["服务入口"]
  Entry --> App["Application"]
  App --> Search["SearchPipeline"]
  App --> Parser["ParserService"]

  Parser --> OCR["OCR"]
  Parser --> Store["Store 接口"]

  Search --> Store
  Search --> Sparse
  Search --> Rerank["Rerank 可选"]

  Store --> DB[("向量库")]
  DB --> Qdrant["Qdrant"]
  DB --> Chroma["Chroma"]
  DB --> Milvus["Milvus"]

  Config["yaml 配置"] --> App
  Config --> Dense
  Config --> Sparse
  Config --> Store
  Config --> Rerank
  Config --> OCR
```

这张图表达的是依赖方向：服务入口不直接绑定某个向量库或模型，搜索流程只依赖 `Store`、`Sparse`、`Rerank` 这些能力接口。实际使用的向量库和模型由 yaml profile 决定。

### 2.2 鉴权架构

系统在应用层区分管理用户和外部系统调用。管理用户登录后使用 User JWT；外部系统业务请求使用 AK/SK HMAC 签名。

```mermaid
sequenceDiagram
  participant User as 管理用户
  participant App as 外部系统
  participant Entry as 服务入口

  User->>Entry: 用户凭证
  Entry-->>User: User JWT
  User->>Entry: Bearer User JWT
  App->>Entry: 业务请求 + AK/SK HMAC 签名
```

管理用户使用用户名和密码换取 User JWT。外部系统使用 `app_id + access_key + secret_key` 对每个业务请求签名，业务入口直接验 access_key/secret_key 和签名。

外部系统签名串固定为 5 行：

```text
METHOD
PATH
TIMESTAMP
BODY_SHA256
APP_ID
```

`PATH` 只使用 URL path，不包含 query string。`signature = hex(hmac_sha256(secret_key, string_to_sign))`。`X-Timestamp` 参与签名，并限制允许的时间偏差；是否启用 nonce 由安全等级决定。

AK/SK 面向外部系统调用，User JWT 面向管理用户。AK/SK 签名里的 `app_id` 决定本次请求访问哪个 chunks collection。`file_id` 写入当前 app collection 的 chunk metadata。

服务入口完成鉴权后，会把请求身份归一成内部身份对象：

```text
admin -> 管理台用户，不绑定 app_id
app   -> 外部系统，绑定 AK/SK 签名里的 app_id
```

业务入口只使用归一后的身份对象判断数据范围。外部系统不能通过请求体切换 `app_id`；管理台用户调用索引、搜索、文件列表或向量数据接口时，需要显式选择 `app_id`，服务端再把它归一成当前请求的数据范围。

### 2.2.1 应用凭证和数据库初始化

外部系统身份由管理台创建。创建 app 时，后端只生成 `access_key` 和 `secret_key`，不创建、不删除、不重建向量库 collection。

```text
collection = {app_id}_chunks
```

应用凭证保存在 PostgreSQL `apps` 表中，多节点后端共享同一份 `app_id`、`access_key`、`secret_key`。

数据库初始化属于数据库管理能力，由管理台在数据库页面显式触发。索引入口不会自动创建 collection；当前 app 尚未初始化数据库时，索引请求返回 `app database is not initialized`。删除 app 只删除 AK/SK 凭证，不删除该 app 的历史向量数据。

业务接口不允许调用方传入 collection 名，也不允许外部系统自行建表。外部系统只保存管理台分配的 `app_id`、`access_key`、`secret_key`。后续索引、查询、删除都根据 AK/SK 签名里的 `app_id` 自动进入对应 collection。

### LangChain 和原生 SDK 边界

LangChain 在系统里负责文档解析复用、文本切分、HuggingFace embedding 封装、Runnable 搜索编排和 Retriever 生命周期事件。开启 LangSmith 后，可以看到搜索请求在 `prepare_plan`、dense/sparse retriever、fusion、dedupe、rerank、format_response 等阶段的链路。

向量库读写和检索由 Store 层直接使用各向量库原生 SDK：

| 向量库               | Store 实现                 | 原生依赖                   | 职责                                                           |
| -------------------- | -------------------------- | -------------------------- | -------------------------------------------------------------- |
| Qdrant               | `store.qdrant.QdrantStore` | `qdrant-client`            | collection 创建、payload index、dense/vector sparse 写入与查询 |
| Chroma local         | `store.chroma.ChromaStore` | `chromadb`                 | 本地 collection、metadata filter、dense 写入与查询             |
| Milvus / Milvus Lite | `store.milvus.MilvusStore` | `pymilvus` / `milvus-lite` | schema、dense/sparse index、scalar index、写入与查询           |

这个边界保证搜索流程只依赖 `Store` 接口，不受第三方封装层的底层能力暴露范围影响。新增向量库时，只需要实现 `Store` 接口；如果该向量库支持 vector sparse，再补对应的 `sparse/*` 适配类。

### 2.3 数据库结构图

```mermaid
flowchart TB
  VectorDB[("向量库")]

  VectorDB --> Chunks["{app_id}_chunks collection"]

  Chunks --> Metadata["metadata: file_id, chunk_index, filename"]
  Chunks --> Vectors["dense vector / 可选 vector sparse"]
```

系统按 app 使用独立 chunks collection 存储 chunk。文件元数据由 PostgreSQL `app_files` 表保存，向量库只负责 chunk 检索。`file_id` 写入 chunk metadata，并在支持的向量库里建立过滤索引。

### 2.4 写入流程图

```mermaid
sequenceDiagram
  participant Client as 外部系统或管理入口
  participant Entry as 写入入口
  participant Consumer as InlineIndexConsumer
  participant Parser as ParserService
  participant Store as Store
  participant DB as 向量库

  Client->>Entry: 上传文件到对象存储
  Entry-->>Client: 返回 s3_url + filename
  Client->>Entry: 提交 s3_url 获取下载地址
  Entry-->>Client: 返回 presigned_url
  Client->>Entry: 同步提交 presigned_url + s3_url
  Entry->>Entry: 生成 file_id
  Entry->>Parser: 下载、解析文件
  Parser->>Parser: 清理文本并切 chunk
  Entry->>Store: insert chunks
  Store->>DB: 写入当前 app collection 的 chunk、vector、metadata.file_id、metadata.s3_url、metadata.created_at
  Entry-->>Client: 返回 file_id
  Client->>Entry: 异步提交 presigned_url + s3_url
  Entry->>Entry: 校验后入队进程内索引队列
  Entry-->>Client: 返回 file_id
  Consumer->>Parser: 后台下载、解析文件
  Parser->>Parser: 清理文本并切 chunk
  Consumer->>Store: insert chunks
  Store->>DB: 写入当前 app collection 的 chunk、vector、metadata.file_id、metadata.s3_url、metadata.created_at
  Client->>Entry: 用 file_id 搜索验证索引就绪
```

写入入口可以同步执行索引，也可以创建异步任务。两种入口都接收 `presigned_url + s3_url`，并允许外部系统传入 UUID 格式的 `file_id`；不传时由 RAG 生成。管理台本地上传链路先通过上传接口生成 `file_id` 并写入对象存储路径，再调用 `/api/open/rag/files/jobs`，因此管理台异步索引必须传入上传阶段返回的 `file_id`。文件名默认可从对象存储地址推导，也允许调用方指定展示名。同步索引成功返回代表已经写入向量库。异步索引入队后立即返回 `file_id`，backend 进程内的索引消费器后台完成下载、解析、切分、embedding 并写入向量库；文件状态可通过管理台文件列表查看。同步入口和异步消费器复用同一套索引执行逻辑。对象存储索引使用 `presigned_url` 做一次性下载，不把临时下载 URL 写入 chunk metadata；稳定的 `s3_url` 会写入 chunk metadata 用于追溯。文件表的 `created_at` 在索引请求进入系统时生成，`indexed_at` 在索引成功时生成；chunk 的 `created_at` 在索引写入时生成并写入 chunk metadata。存储层统一保存 UTC 时间，对外返回前再转换成本机或容器时区。

异步索引任务保存在 backend 进程内的 `queue.Queue`（标准库线程安全队列）里，容量 10（硬编码默认值，不走环境变量）。入队端点在请求线程里直接 `put_nowait`，消费器在普通工作线程里阻塞读取任务，两端跨线程安全。任务入队成功即被接受，由进程内消费器串行消费，实际索引并发固定为 1；队列已满时入队请求返回 429。RAG 不假设所有上游系统都有自己的队列、限流和重试能力；内部队列是 RAG 服务的资源保护边界，用来削峰并控制解析、embedding 和向量库写入并发。进程内队列不做持久化，backend 重启后未完成的任务会丢失；原始文件仍在对象存储，可以重新触发索引。每个 `app_id` 对应独立 collection，外部系统只要按 UUID 规约生成 `file_id`，就不会和其他 app 的同名文件发生跨系统冲突。

Docker 开发环境使用 MinIO 模拟 S3。MinIO 提供本地 bucket 和对象下载能力，服务入口可以在本地联调时根据 `s3_url` 生成后端可访问的短期下载地址。生产环境里，重签通常由业务系统或对象存储网关完成，RAG 仍只消费 `presigned_url + s3_url`。

### 2.5 查询流程图

```mermaid
flowchart TB
  Query["Search Request"] --> Plan["SearchPlan"]
  Plan --> Filter{"file_ids 是否传入?"}
  Filter -->|是| FileFilter["metadata.file_id 过滤"]
  Filter -->|否| Full["全库搜索"]
  FileFilter --> Retrieve["Dense / Sparse / Hybrid"]
  Full --> Retrieve
  Retrieve --> Dedupe["去重"]
  Dedupe --> NeedRerank{"rerank=true?"}
  NeedRerank -->|是| Rerank["Rerank 重排"]
  NeedRerank -->|否| Format["格式化返回"]
  Rerank --> Format
```

查询只查当前调用身份对应 app 的 chunks collection。`file_ids` 作为 metadata filter 缩小候选范围；dense / sparse / hybrid 在同一个范围内检索。hybrid 统一为 dense 和 sparse 两路并发后在应用层做 RRF 融合；开启 rerank 时，再对候选结果做二次排序。`sparse` 由 profile 选择具体实现，例如 BGE-M3 sparse vector 或 OpenSearch BM25。

搜索入口返回业务搜索结果和本次搜索总耗时。搜索完成后，后端把链路信息写入内存 ring buffer，供诊断入口读取最近搜索请求的总耗时、结果数和阶段耗时。

### 2.6 运行监控

运行监控提供轻量系统状态快照，包括运行状态、组件状态、collection、索引配置和组件绑定信息。监控状态不读取 chunk，不做文件数或 chunk 数统计。搜索链路快照面向单次查询诊断。

真正会影响索引结构的配置，例如 store、dense、sparse、collection，不允许在运行监控里直接修改。查询级参数，例如 mode、top_k、fetch_k、dense_weight、sparse_weight、rerank 开关，继续随搜索请求传入。

监控能力按三类组织：

- 组件：Store、Dense、Sparse、Rerank、OCR、Parser 的状态和绑定模型。
- 链路：最近若干次搜索的总耗时和各阶段耗时。

组件状态统一为四态：`ready` 表示组件已加载完成，`loading` 表示启用但尚未 ready，`disabled` 表示配置未启用，`error` 表示启动或加载失败。Sparse 作为一个组件表达，显示运行 profile 绑定的 sparse 类型和模型。Parser 显示当前标准解析能力状态。

模型切换属于配置管理能力，不属于运行监控能力。

向量数据查看能力直接分页读取向量库 chunk 数据，展示 chunk 主键、`file_id`、`s3_url`、`filename`、`chunk_index` 和完整 chunk 文本。管理台文件列表由 database 组件（PostgreSQL `app_files` 表）提供分页元数据，展示 `file_id`、`filename`、`s3_url`、`size`、`chunk_count`、索引状态、失败原因、创建时间和索引成功时间。管理台按 `file_id` 删除文件时同时删除向量库 chunks、软删 `app_files` 记录并删除该 MinIO/S3 前缀下的对象；上游删除文件接口删除向量库 chunks 并软删 `app_files` 记录，不动 MinIO 对象。

### 2.7 进程内索引消费器

异步索引由 backend 进程内的 `InlineIndexConsumer`（`index/consumer.py`）消费，没有独立 index-worker 进程，也没有 Celery/Redis。FastAPI lifespan 启动消费器；索引与查询共享同一份 `Application`，模型只在 backend 进程内加载一份。

| 边界                              | 实现                                                                                                                                                           |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 入队                              | `index.queue.enqueue_index_job()` 向进程内 `queue.Queue`（`maxsize=10`，硬编码）`put_nowait`；入队前写 `app_files.status=queued`                            |
| 消费                              | `InlineIndexConsumer`，lifespan 启动 1 个普通 daemon 线程，并发固定为 1                                                                                        |
| 执行                              | 工作线程同步执行下载、解析、embedding 和向量库写入，不再包 executor 假超时                                                                                    |
| 重试                              | job 字典内 `retry_count`，小于 2 时重新入队尾（最多重试 2 次，硬编码），超过后写 `app_files.status=failed`                                                     |
| 不可恢复错误                      | app 数据库未初始化、文件格式不支持等 `ValueError` 写 `app_files.status=failed`，不重试                                                                         |
| 队列满                            | `put_nowait` 抛 `QueueFull`，入队接口返回 429                                                                                                                  |
| 任务记录 / 列表 / 状态 / 事件推送 | 无 job_id、无任务记录、无状态接口、无 SSE；文件级状态落在 `app_files.status/error/indexed_at`                                                                 |
| 重启                              | 进程内队列随进程清空，接受丢任务；原始文件仍在对象存储，可重新触发索引                                                                                         |
| 停止                              | lifespan 停止时置位 stop_event、等待循环退出，并注销模块级单例；此后入队直接抛 `RuntimeError`                                                                  |

`InlineIndexConsumer` 不做应用层假超时；长任务由工作线程同步跑完。`add_file_chunks` 按 `file_id` delete-then-upsert 幂等，重试会覆盖前一次失败前可能写入的旧 chunks。

#### 2.7.1 Application 两阶段启动

`Application` 拆为模型阶段和运行连接阶段：

```python
def load_models(self):
    dense.start()
    sparse.start()
    rerank.start()  # profile 启用时
    ocr.start()

def init_connections(self):
    store.start()
    search.start()

def start(self):
    load_models()
    init_connections()
```

`load_models()` 只负责模型、分词器和 OCR runtime；`init_connections()` 负责向量库连接、collection 检查和搜索 pipeline 运行绑定。backend 进程调用 `Application.start()` 按顺序执行两个阶段；索引消费器复用同一份 `Application`，不单独加载模型。

### 2.8 API 分层

RAG HTTP 入口统一使用 `/api/open/rag/*` 路径前缀，LLM 入口统一使用 `/api/open/llm/*` 路径前缀。nginx 只负责按前缀转发，不改写路径；直连服务和经过 nginx 的 API 形态一致。

RAG 路由按调用方使用不同认证：

- 管理台前端使用 User JWT。
- 上游系统使用 AK/SK 请求签名。

搜索、索引、异步索引、删除文件这几个业务端点同时接受 JWT 或 AK/SK，业务逻辑收敛在同一个实现函数里。管理面接口（apps、monitor、config、upload、presign、files 列表等）只接受 JWT。

上游系统有自己的对象存储时，只需要调用 `POST /api/open/rag/files/jobs`，自己生成 `presigned_url` 传入。管理台前端的本地上传链路是 upload → presign → files/jobs 三步；presign 让内部上传的文件也走统一的 `presigned_url` 契约。

主要端点：

| 业务                            | 路径                                      | 认证           | 实现                  |
| ------------------------------- | ----------------------------------------- | -------------- | --------------------- |
| 同步索引                        | `POST /api/open/rag/files`                | JWT 或 AK/SK   | `_index_object()`     |
| 异步索引                        | `POST /api/open/rag/files/jobs`           | JWT 或 AK/SK   | `_create_index_job()` |
| 搜索                            | `POST /api/open/rag/search`               | JWT 或 AK/SK   | `_search()`           |
| 删文件                          | `DELETE /api/open/rag/files/{file_id}`    | JWT 或 AK/SK   | `delete_file()`       |
| 上传                            | `POST /api/open/rag/upload`               | JWT            |                        |
| 生成下载签名                    | `POST /api/open/rag/presign`              | JWT            |                        |
| 文件列表                        | `GET /api/open/rag/files`                 | JWT            |                        |
| 向量数据 / 应用 / 监控等管理面 | `/api/open/rag/chunks`、`/api/open/rag/apps`、`/api/open/rag/monitor` 等 | JWT | |

两处不对称需要说明：

- 删除语义：JWT 管理台删除会在删索引之外删除 MinIO/S3 中 `uploads/{app_id}/{file_id}/` 前缀下的原始对象；AK/SK 删除只清理当前 app 向量库里的 chunks（见 2.6）。
- 搜索响应：JWT 管理台响应保留 metadata，AK/SK 响应只返回上游需要的精简字段。

---

## 3. 配置目录

后端使用 yaml profile 描述一套完整运行组合。配置读取代码和配置结构校验代码与具体 profile 解耦，运行时由环境选择一个 profile 启动。

每个运行 profile 使用一个 yaml 文件。yaml 文件固定一种索引结构，不在同一个文件里放多套 dense 或 vector sparse 候选。真正会影响索引结构的组件，例如 dense 和 vector sparse，必须通过切换 profile 或重建索引改变。不会改变索引结构的组件，例如 rerank、ocr，可以继续在同一个 yaml 里用候选项和 `enable` 表达。

每个组件都显式写 `import_path`。组件名负责表达“我要哪种能力”，`import_path` 负责表达“这类能力由哪个 Python 类实现”。这样配置文件里能直接看出实现位置，也方便以后把组件迁移成插件。

`bootstrap.py` 负责应用启动和关闭。`container.py` 负责按配置组装 dense、sparse、store、search、rerank、ocr。它们不保存具体业务规则，也不把某个模型或向量库写死到搜索逻辑里。

profile 名只作为运维识别入口；真正的索引结构以 yaml 里的 store、dense 和 sparse 配置为准。业务 collection 名不写在 yaml 里，由后端根据 `app_id` 统一生成。

---

## 4. 配置结构

profile 结构示例：

```yaml
dense:
  name: <dense_name>
  model_name: <dense_model>
  import_path: <dense_class>

sparse:
  type: <sparse_type>
  import_path: <sparse_class>

store:
  type: <store_type>
  import_path: <store_class>

search:
  default_mode: <dense|sparse|hybrid>
  top_k: <max_results>
  fetch_k: <rerank_candidates>
  dense_weight: <hybrid_dense_weight>
  sparse_weight: <hybrid_second_backend_weight>
  rrf_k: <rrf_constant>

logging:
  level: <log_level>
  search_trace: <true|false>

rerank:
  <rerank_name>:
    enable: <true|false>
    model_name: <rerank_model>
    import_path: <rerank_class>

ocr:
  <ocr_name>:
    enable: <true|false>
    model_name: <ocr_model>
    import_path: <ocr_class>
```

不同向量库的连接字段不强行统一。统一的是 `store` 暴露给 `search` 的能力。

同一个 profile 只声明一种 store 和一种 sparse 后端。运行形态不同、索引结构不同或模型组合不同，都应该拆成不同 profile，不在同一个 yaml 里用 `enable` 切换会改变索引结构的组件。

Milvus 的索引策略按运行形态区分：

- Milvus store 使用 `pymilvus.MilvusClient` 创建 schema、索引、写入和查询。
- Standalone 和 Lite 使用不同索引策略，由 Store 实现按运行形态选择。
- sparse 索引按 sparse 类型选择对应的 Milvus sparse index 和 metric。
- `file_id` 是过滤字段，创建 collection 时会额外建 scalar index。

---

## 5. 模块目录

目录按职责分层：

```text
backend/
  main.py
  api/
    routes/
    service.py
    runtime.py
    schemas.py
  bootstrap.py
  container.py
  loader.py
  schema.py
  config/
  index/
  dense/
  sparse/
  store/
  search/
  rerank/
  ocr/
  tokenizer/
```

模块职责：

| 模块                 | 职责                                                                             |
| -------------------- | -------------------------------------------------------------------------------- |
| `main.py`            | FastAPI 应用装配、生命周期绑定和路由注册                                        |
| `api/routes/`        | HTTP 路由入口，按 auth、apps、config、files、monitor、logs、traces、search 拆分 |
| `api/services/`      | HTTP 业务编排，按 auth、apps、config、files、health、monitor、logs、traces、search 分域 |
| `api/runtime.py`     | 进程级 Runtime，持有当前 Application、启动策略和内置索引消费器                  |
| `api/schemas.py`     | HTTP 请求模型                                                                    |
| `bootstrap.py`       | 创建 Application，管理组件启动和关闭                                             |
| `container.py`       | DI 容器，按配置组装组件并注入依赖                                                |
| `config.py`          | 应用配置入口，暴露搜索参数、模型路径、向量库配置                                 |
| `device.py`          | 检测当前可用计算设备；有 GPU 时优先使用 GPU，否则使用 CPU                        |
| `scripts/download_models.sh` | 下载或准备本地模型目录                                                           |
| `loader.py`          | 读取运行环境指定的 yaml profile                                                  |
| `schema.py`          | 校验配置结构和默认值                                                             |
| `index/`             | 文件索引领域，负责索引请求校验、入队、消费、对象存储下载、解析和写入向量库       |
| `parser/`           | 文件解析、文本清理、表格归一化和 chunk 生成                                     |
| `parser/service.py` | Parser 生命周期组件                                                             |
| `parser/document.py` | 文件格式分发入口，调用具体格式 parser                                          |
| `parser/pdf.py`    | PDF 解析，调用 MinerU 并抽取内嵌图片                                            |
| `parser/docx.py`   | DOCX 解析，读取正文段落并使用 MinerU 解析表格和图片                            |
| `parser/excel.py`  | XLSX 解析，调用 MinerU 并抽取内嵌图片                                           |
| `parser/markdown.py` | Markdown 原生解析                                                              |
| `parser/image.py`  | 图片文件和 ImageBlock 解析                                                      |
| `parser/text.py`   | TXT 读取和通用文本 chunk 工具                                                   |
| `parser/text_splitter.py` | 文本清理和普通文本 chunk 切片工具                                             |
| `parser/mineru.py` | MinerU 文档解析适配，负责模型配置、加载和调用 MinerU SDK                      |
| `parser/table_transform.py` | 表格结构归一化，把 MinerU JSON/HTML 表格转换为 Markdown 表格文本              |
| `parser/table_splitter.py` | 表格渲染为 Markdown 表格文本                                                  |
| `dense/`             | 生成 dense 向量                                                                  |
| `sparse/`            | 执行应用内 sparse 检索，或生成 sparse vector                                     |
| `store/`             | 连接向量库，负责写入、删除、列表、dense 查询、可选 sparse 查询                   |
| `search/`            | SearchPipeline 和 SearchRunner，负责检索流程、并发查询、去重、融合和 rerank 调用 |
| `rerank/`            | 对候选结果做二次排序                                                             |
| `ocr/`               | 可选 OCR 适配组件，当前标准文档解析链路不依赖它                                   |
| `tokenizer/`         | 分词能力接口和 jieba 实现                                                        |

命名规则：

- `dense/` 只负责 dense vector。
- dense 能力接口命名为 `Dense`。
- HuggingFace dense 实现命名为 `HuggingFaceDense`。
- dense 模型通过 yaml 的 `model_name` 指定，启动时解析到 `models/` 下的实际路径。
- 复用模型能力放在共享模块里，向量库 sparse 适配按 Store 拆开，不放在 `dense/` 里。

---

## 6. 组件组装

启动目标流程：

```text
1. 读取运行环境指定的配置文件
2. 解析 yaml
3. 校验配置
4. 创建 DI 容器
5. 容器按配置创建 dense、sparse、store、search、rerank、ocr
6. FastAPI 进程启动
7. 后台初始化线程按顺序启动 Application 组件
8. 初始化成功后 application.ready=true
```

示意代码：

```python
config = load_app_config()
container = create_container(config)

dense = container.dense()
sparse = container.sparse()
store = container.store(dense=dense, sparse=sparse)
search = container.search(store=store, sparse=sparse)
rerank = container.rerank()
ocr = container.ocr()
```

`container.py` 使用 DI 容器组装组件。配置里的组件名映射到容器 provider，provider 负责创建实现并注入依赖。`bootstrap.py` 只管理 Application 生命周期。FastAPI 启动后由后台线程初始化 Application；如果数据库暂时不可用，后端进程不退出，后台线程按退避间隔继续重试。搜索流程只依赖组件能力，不直接依赖实现类。

`Application` 使用两阶段启动：`load_models()` 启动 dense、sparse、rerank、ocr；`init_connections()` 启动 store、search。`Application.start()` 是兼容入口，顺序等同于先加载模型再初始化运行连接。其中 `rerank` 只有在 profile 启用时才启动。`Application.stop()` 按反向顺序停止组件。

Store 和 Search 不负责偷偷启动 dense 或 sparse，只校验依赖组件已经 ready。这样初始化和查询严格分离：模型只在启动阶段加载，查询阶段不会懒加载模型。启动某个组件失败时，`Application` 会记录对应的 `component_errors`，监控状态把组件标成 `error`。

### 6.1 database 组件

`database` 是与 `store`、`dense` 等平级的一等组件，由 DI 容器按配置装配、`Application` 统一管理生命周期。PG 只承载文件元数据，chunk 正文和向量仍存向量库。

`database/base.py` 定义 `Database` Protocol 与数据模型（`FileRecord`/`FilePage`），并提供测试用的内存实现 `FakeDatabase`。生产实现是 `database/postgres.PostgresDatabase`（psycopg3 连接池），`start()` 幂等建 `app_files` 表：`app_id` 租户隔离，`(app_id, file_id)` 唯一约束，`status` 记录索引生命周期，`error` 记录失败原因，`indexed_at` 记录索引成功时间，`deleted_at` 记录软删除时间。

关键语义：

- 软删除：`soft_delete_file` 只置 `deleted_at` 不物理删除；列表查询带 `deleted_at IS NULL` 过滤。
- 状态推进：索引请求进入系统时 `create_file` 写入 `queued`；consumer 开始处理时 `mark_file_indexing` 写入 `indexing`；索引成功时 `upsert_file` 写入 `success`、`chunk_count`、`size` 和 `indexed_at`；索引失败时 `mark_file_failed` 写入 `failed` 和 `error`。
- upsert 复活：`upsert_file` 用 `ON CONFLICT (app_id, file_id) DO UPDATE`，重新索引同一 `file_id` 时自动清除 `deleted_at`，软删记录复活。
- 单向 keyset 纯 id 游标：`list_files` 用表主键 `id`（BIGSERIAL，与 `created_at` 同序）做游标，列表按 `created_at DESC, id DESC` 展示；下一页用 `id < cursor`，多取 1 条判断 has_more，无 COUNT 无页码。
- e2e 用 FakeDatabase：e2e 测试在 `conftest.py` 注入 `FakeDatabase`，不依赖真实 PG。

---

## 7. Store 能力

`store/base.py` 定义搜索流程需要的统一能力。不同向量库的连接方式可以不同，但对 `search` 暴露的方法保持一致。

目标能力：

```python
class Store:
    def start(self) -> None: ...
    def stop(self) -> None: ...

    def add_file_chunks(self, chunks: list[dict], file_id: str) -> int: ...
    def delete_file_chunks(self, file_id: str) -> int: ...

    def get_total_chunks(self, file_ids: list[str] | None = None) -> int: ...
    def get_search_documents(self, metadata_filter: object) -> list[dict]: ...
    def build_file_filter(self, file_ids: list[str] | None = None): ...
    def search_dense(self, query: str, limit: int, metadata_filter: object) -> list[dict]: ...
    def search_sparse(self, query: str, limit: int, metadata_filter: object) -> list[dict]: ...
    def search_hybrid(
        self,
        query: str,
        limit: int,
        metadata_filter: object,
        dense_weight: float,
        sparse_weight: float,
        rrf_k: int,
    ) -> list[dict]: ...
    def sparse_uses_store(self, sparse: object | None = None) -> bool: ...
```

`SearchPipeline` 只依赖 `Store` 接口，不直接依赖 `store.qdrant`、`store.chroma`、全局 store 模块函数或向量库 SDK。各 Store 实现内部使用原生 SDK 完成 collection、索引、写入、删除、列表和查询。`simple_bm25` sparse 使用 `get_search_documents()` 取文本，再交给 `sparse/simple_bm25.py` 排序；`bge_m3` sparse 只用于支持稀疏向量的 store，由对应向量库执行 sparse 查询；`opensearch_bm25` sparse 由 OpenSearch 执行 BM25 检索。

写入规则：

- 每次索引生成一个新的全局 `file_id`。
- 更新文件等价于删除旧 `file_id` 后重新索引。
- `file_id`、`chunk_index`、`filename` 必须写入 chunk metadata。
- 不同 `file_id` 的写入可以并发。
- 读操作可以并发。

---

## 8. Sparse 能力

每个 profile 只配置一个 `sparse` 后端。`sparse` 属于索引结构的一部分，不做运行时切换；要切换 sparse 类型，需要使用对应 profile 和对应 collection。搜索流程里统一表现为 Sparse Retriever，但内部有两种路线：

```text
应用内 Sparse Retriever
  -> 先从 store 取候选文本
  -> `simple_bm25` sparse 使用 `tokenizer=jieba` 打分

索引型 Sparse Retriever
  -> 查询向量库 sparse vector / 向量库内置 sparse / OpenSearch BM25 能力
```

这两种都属于检索节点，都会放在 SearchPipeline 的 Retriever 位置；区别只是 sparse 分数在哪里计算。
benchmark 报告中的 `sparse_impl` 使用 `app` 和 `vector` 区分这两条路线。

配置读取结果包含 profile 固定使用的 sparse 后端：

```json
{
  "sparse": {
    "name": "<sparse_name>",
    "tokenizer": "<tokenizer>"
  }
}
```

`simple_bm25` sparse：

```yaml
sparse:
  simple_bm25:
    enable: true
    tokenizer: <tokenizer>
    import_path: sparse.simple_bm25.SimpleBM25Sparse
  bge_m3:
    enable: false
  opensearch_bm25:
    enable: false
```

流程：

```text
1. store 按 file_ids 过滤后取候选文本
2. sparse 在应用内分词和打分
3. 返回排序后的结果
```

应用内 BM25 sparse 流程：

```text
1. tokenizer 对查询和候选文本分词
2. 去掉纯标点和单个汉字这类不稳定命中项
3. BM25 对候选文本打分排序
4. 不返回零命中文本
```

应用内 `simple_bm25` sparse 直接使用 `rank_bm25` 计算分数，不使用 LangChain `BM25Retriever.invoke()`。原因是 `BM25Retriever.invoke()` 只返回 `Document` 列表，不直接返回 BM25 分数；搜索流程需要分数做过滤、排序和 hybrid 融合。

向量库检索和应用内 BM25 的 score 来源不同：

```text
dense 检索
  -> 使用各向量库 store 的原生查询接口
  -> score 来自向量库

vector sparse
  -> 使用向量库 sparse 查询
  -> score 来自向量库

应用内 simple_bm25 sparse
  -> 使用 rank_bm25 在应用进程里计算
  -> score 来自 BM25 关键词打分
```

模型型 vector sparse 流程：

```text
1. 上传时 sparse 生成 sparse vector
2. store 把 sparse vector 写入向量库
3. 查询时 sparse 生成 query sparse vector
4. store 执行 sparse vector 查询
```

向量库内置 sparse 流程：

```text
1. 上传时按向量库 analyzer 从文本生成 sparse 索引数据
2. 查询时向量库对查询文本执行同一套 analyzer
3. sparse 由向量库执行；hybrid 仍由 SearchPipeline 对 dense 和 sparse 结果做应用层融合
```

这个设计可以兼容：

```text
任意 Store + 应用内 sparse
支持 sparse vector 的 Store + 模型型 vector sparse
支持内置 sparse 的 Store + 向量库内置 sparse
```

---

## 9. 知识集合

系统对每个 app 使用一个知识集合：

| 集合              | 用途                          |
| ----------------- | ----------------------------- |
| `{app_id}_chunks` | 存储当前 app 的所有文件 chunk |

collection 名由后端根据 `app_id` 生成。文件范围通过 `file_id` metadata filter 表达；不同 app 的数据落在不同 collection。不同模型组合如果索引结构不兼容，必须使用不同 profile 或重建对应 app collection，避免新旧向量混在一个索引里。

---

## 10. Payload Metadata

每条 chunk 在向量库里分成三类数据：

| 类型     | 存什么                    | 例子                                           |
| -------- | ------------------------- | ---------------------------------------------- |
| 正文内容 | 被检索、展示的 chunk 文本 | `content` / `documents` / `text`               |
| metadata | 描述这段正文的附加信息    | `file_id`、`filename`、`chunk_index`、`s3_url` |
| vector   | 正文内容生成出来的向量    | dense vector、可选 sparse vector               |

chunk metadata：

```json
{
  "file_id": "<file_id>",
  "filename": "<filename>",
  "chunk_index": 0,
  "s3_url": "<s3_url>"
}
```

字段约定：

| 字段          | 类型           | 说明                                 |
| ------------- | -------------- | ------------------------------------ |
| `file_id`     | keyword/string | 必填，搜索过滤用，要建索引           |
| `filename`    | keyword/string | 必填，搜索结果展示用                 |
| `chunk_index` | integer        | 必填，文件内 chunk 序号，不建索引    |
| `s3_url`      | string         | 对象存储来源地址，用于追溯，不建索引 |

放进 metadata 不等于自动有高效过滤索引。只给 `file_id` 建过滤索引：

| 向量库       | `file_id` 过滤索引策略                                                       |
| ------------ | ---------------------------------------------------------------------------- |
| Qdrant       | 创建 payload index：`metadata.file_id`                                       |
| Milvus       | 创建 scalar index：`file_id` 字段                                            |
| Chroma local | metadata 写入后由 Chroma 本地 SQLite metadata 表维护索引；代码不额外声明索引 |

`filename`、`chunk_index` 会随每条 chunk 一起保存，搜索结果可以返回这些字段；它们不作为搜索过滤条件，不建索引。

chunk 文本会随分块一起写入向量库。不同向量库的原生字段不同，但 Store 对搜索流程统一返回 `content`：

| 向量库               | 原生保存位置                     | Store 返回字段 |
| -------------------- | -------------------------------- | -------------- |
| Qdrant               | payload 的 `content`             | `content`      |
| Chroma local         | Chroma collection 的 `documents` | `content`      |
| Milvus / Milvus Lite | scalar 字段 `text`               | `content`      |

向量库里保存的是解析后的 chunk 文本，不保存完整原始文件内容。上传接口把原文件写入对象存储；对象存储索引接口不保存 `presigned_url`。

---

## 12. 文档解析与切片

上传文件先解析成统一 block，再切成 chunk 写入 store。文件入口先按扩展名白名单拒绝不支持格式；进入具体 parser 后再做真实文件格式校验，避免伪装后缀的文件进入解析或向量库写入。系统只保留标准解析：PDF、DOCX、XLSX、图片文件和文档内嵌图片由 MinerU pipeline 做结构化解析，Markdown 由原生 parser 解析。

Parser 是 `Application` 生命周期内的正式组件，由 `container.py` 构造，并保留 OCR 兼容注入。`Application.load_models()` 启动 Parser；索引阶段通过 `application.parser.parse_file()` 解析文件，不直接调用全局解析函数。

Parser 代码按领域边界拆分：

```text
parser/
├── service.py
│   └── ParserService：Application 生命周期组件
├── document.py
│   └── DocumentParser：按文件类型分发，调用对应 BlockParser 类
├── schema.py
│   └── 统一内部结构：TextBlock / TableBlock / ImageBlock
├── text.py
│   └── TextBlockParser：TXT 读取为 TextBlock；保留通用文本切片工具
├── pdf.py
│   └── PdfBlockParser：MinerU 输出 TextBlock / TableBlock，内嵌图片输出 ImageBlock 后展开
├── image.py
│   └── ImageBlockParser：图片文件和 ImageBlock 调用 MinerU 输出 TextBlock / TableBlock
├── markdown.py
│   └── MarkdownBlockParser：原生解析 Markdown 正文和 pipe table，图片引用输出 ImageBlock 后展开
├── docx.py
│   └── DocxBlockParser：python-docx 读取正文顺序和段落，MinerU 解析表格和内嵌图片
├── excel.py
│   └── ExcelBlockParser：MinerU 输出 TextBlock / TableBlock，内嵌图片输出 ImageBlock 后展开
├── mineru.py
│   └── MinerU 适配层：调用 MinerU 并读取 content list
├── table_transform.py
│   └── MinerU 表格输出转换：HTML/rows -> Markdown 表格文本 -> TableBlock
├── normalizer.py
│   └── blocks 结构纠偏：空块过滤、连续文本合并、章节标题识别
├── table_splitter.py
│   └── 表格结构渲染为完整 Markdown 表格
├── text_splitter.py
│   └── 普通文本清理和切片
├── validation.py
│   └── DOCX / XLSX / PDF / 图片真实格式校验
└── chunker.py
    └── TextBlock / TableBlock -> 最终 chunk document
```

真实格式校验在具体格式入口执行：DOCX 检查 zip 包和 Word 目录结构；XLSX 检查 zip 包和 Excel 目录结构；PDF 在解析前用 PyMuPDF 打开验证；图片在交给 MinerU 前用 Pillow `Image.verify()` 验证。TXT / Markdown 按文本格式处理，校验重点是可读取且非空。

统一解析链路：

```text
文件
└── DocumentParser
    ├── PDF：MinerU -> TextBlock / TableBlock，内嵌图片 -> ImageBlock -> MinerU
    ├── DOCX：python-docx -> TextBlock，MinerU -> TableBlock，内嵌图片 -> ImageBlock -> MinerU
    ├── XLSX：MinerU -> TextBlock / TableBlock，内嵌图片 -> ImageBlock -> MinerU
    ├── 图片：MinerU -> TextBlock / TableBlock
    ├── Markdown：原生 parser -> TextBlock / TableBlock，图片引用 -> ImageBlock -> MinerU
    └── TXT：文本读取 -> TextBlock
        ↓
    TextBlock / TableBlock
        ↓
    normalizer
        ↓
    chunker
        ↓
    chunk document(content, id, metadata)
```

图片文件和文档内嵌图片使用 MinerU 解析，解析结果同样进入统一 `TextBlock` / `TableBlock` 管线。图片里的普通文字会作为 text chunk 写入；图片里的表格如果 MinerU 输出表格结构，则转换为完整 table chunk。

Markdown 由原生 parser 读取正文和标准 pipe table；PDF、Excel 和图片由 MinerU 输出结构化 content list。DOCX 正文段落由 python-docx 按 Word body 顺序读取，表格仍使用 MinerU 输出。系统把表格 HTML 或 rows 解析成统一行列结构，再转换成 Markdown 表格文本。这样可以复用同一套表格切片逻辑，避免 Markdown、Word、Excel、PDF 和图片各写一套表格处理代码。

MinerU 是 PDF、Word、Excel 和图片的结构化解析实现细节，不作为独立业务 parser 暴露。

MinerU 使用 pipeline 后端。运行时模型根目录是实体目录 `models/mineru/pipeline`，`models/mineru/mineru.json` 的 `models-dir.pipeline` 指向该目录。后端判断 MinerU 可用时检查 Python 包、配置文件和 pipeline 模型目录。

模型加载和模型使用分离：应用启动阶段加载 dense、sparse、rerank、OCR 和可用的 MinerU 模型；索引阶段只使用已经加载的模型，不在请求处理中懒加载 MinerU，也不通过子进程执行 MinerU CLI。MinerU 调用走 Python SDK，复用当前进程里的 pipeline 模型单例。

最终 chunk 中，普通正文走文本切片；每张逻辑表完整写入一个 table chunk。表格块内部如果出现“标题行 + 新表头”，会拆成多张逻辑表，每张逻辑表仍然各自完整写入一个 chunk。表格 header/footer 上下文分别来自前后相邻文本块，header 从前文向后截取，footer 从后文向前截取。向量库 `content` 保存 Markdown 表格文本。

切片参数由配置决定：

```yaml
parser:
  text:
    chunk_size: 500
    chunk_overlap: 80
  table:
    header_backward_chars: 160
    footer_forward_chars: 160
```

| 参数 | 含义 |
| --- | --- |
| `parser.text.chunk_size` | 普通文本 chunk 字符上限 |
| `parser.text.chunk_overlap` | 普通文本相邻 chunk 重叠字符数 |
| `parser.table.header_backward_chars` | 表格 header 从前一个文本块末尾截取的字符数 |
| `parser.table.footer_forward_chars` | 表格 footer 从后一个文本块开头截取的字符数 |

切片按中文文档常见边界拆分，优先使用段落、换行、中文句号、感叹号、问号、分号、逗号和空格。

一个逻辑表就是一个完整 table chunk。表格过大导致回答阶段上下文不足时，由上层调用方决定是否摘要、筛选或二次处理。

解析后的文本会做 Unicode 归一化，并去掉中文字符之间由 PDF 提取产生的多余空格。

---

## 13. 搜索计划

`SearchPlan` 描述一次搜索：

```python
SearchPlan(
    query="查询内容",
    mode="hybrid",
    top_k=max_results,
    rerank=False,
    fetch_k=rerank_candidates,
    dense_weight=hybrid_dense_weight,
    sparse_weight=hybrid_second_backend_weight,
    rrf_k=rrf_constant,
    file_ids=["<file_id>"],
)
```

字段说明：

| 字段            | 说明                                        |
| --------------- | ------------------------------------------- |
| `query`         | 查询文本                                    |
| `mode`          | `dense` / `sparse` / `hybrid`               |
| `top_k`         | 最多返回条数                                |
| `rerank`        | 是否使用 rerank                             |
| `fetch_k`       | rerank 候选池大小                           |
| `dense_weight`  | 本次 hybrid 查询的 dense 权重               |
| `sparse_weight` | 本次 hybrid 查询第二路召回权重              |
| `rrf_k`         | 本次 hybrid 查询的 RRF 参数                 |
| `file_ids`      | 查询文件范围；不传时搜索当前 app collection |

---

## 14. 搜索执行

检索阶段数量：

```text
rerank=false -> retrieve_limit = top_k
rerank=true  -> retrieve_limit = fetch_k
```

执行流程：

```text
1. 检查 application 已 ready
2. SearchPlan 进入 SearchPipeline Runnable
3. prepare_plan 计算 retrieve_limit
4. retrieve 按当前调用身份的 app_id 选择 collection，并按 file_ids 构造 metadata_filter
5. hybrid 时 dense / sparse 使用 RunnableParallel 并发查询
6. fusion 对 dense / sparse 结果做加权倒数排名融合
7. dedupe 按 chunk id 去重
8. rerank=true 时，对合并候选执行 rerank
9. format_response 最多返回 top_k 条
```

Runnable 结构：

```text
SearchPipeline RunnableSequence
  prepare_plan
  retrieve
    dense/sparse Retriever RunnableParallel
    fusion
  dedupe
  rerank
  format_response
```

dense 和 sparse 检索节点使用 LangChain `BaseRetriever`。这些节点会触发 LangChain retriever 生命周期事件，开启 LangSmith 后会显示为 retriever run。`prepare_plan`、`fusion`、`dedupe`、`rerank`、`format_response` 不是检索动作，继续使用普通 Runnable 阶段。

三种检索模式：

```text
dense  -> Dense Retriever 调用 Store.search_dense()，由具体 store 实现 dense 查询
sparse -> 应用内 Sparse Retriever 执行 simple_bm25，或索引型 Sparse Retriever 调用向量库 sparse / OpenSearch BM25 查询
hybrid -> dense + sparse 并发后应用层 RRF 融合；sparse 可以是 simple_bm25、bge_m3 或 opensearch_bm25
```

并发规则：

- hybrid 内部 dense 和 sparse 可以并发查询。
- rerank 在候选合并去重后执行。

排序规则：

- dense 按向量库返回的 dense 相似度排序。
- sparse 按 sparse 自身分数排序。
- hybrid 按加权倒数排名融合排序。
- rerank 开启时，最终顺序由 rerank 决定。

`top_k` 是最多返回条数，不是必须填满。sparse 不补满，查不到就可以返回空；dense 和 hybrid 如果不做额外相关性判断，本质上都是 top_k 排序，在库里有足够文档时可能返回到 `top_k` 条，不保证结果真的相关。

`rrf_k` 是 hybrid 的 RRF 融合参数，用于计算 dense/sparse 融合分。它不是返回条数，也不是候选池大小。

---

## 15. 日志

日志配置跟随业务 yaml：

```yaml
logging:
  level: <log_level>
  max_bytes: <max_bytes>
  backup_count: <backup_count>
  search_trace: <true|false>
```

默认只输出到 stdout，不写本地文件。如果配置 `file`，则同时写 stdout 和本地滚动文件：

```yaml
logging:
  level: <log_level>
  file: <log_file>
  max_bytes: <max_bytes>
  backup_count: <backup_count>
  search_trace: <true|false>
```

日志格式统一是 JSONL，一行一条 JSON。普通应用日志和搜索链路日志使用同一个格式，通过 `logger` 和 `event` 区分：

```json
{"logger":"rag.app","event":"startup_ready","message":"Startup model load done"}
{"logger":"rag.trace","event":"search_trace","app_id":"app_a","query":"查询内容","mode":"hybrid","elapsed_ms":123.4}
```

`rag.app` 记录启动、关闭、模型加载、OCR 加载、上传、删除、异常等应用事件。`rag.trace` 记录一次搜索的链路信息，包括查询参数、总耗时、结果数量和阶段耗时。`search_trace: false` 时不输出搜索链路日志。

运行日志和搜索 trace 都通过 JSONL 输出，由 Promtail 采集到 Loki。

Docker 模式下，应用仍输出 JSONL 到 stdout。Docker Compose 使用 `json-file` driver 按大小滚动容器日志，避免日志无限增长。

LangSmith 和本地 JSONL 日志可以同时开启。LangSmith 用于查看 LangChain Runnable / Retriever 的可视化链路；JSONL 日志是本地和生产环境都能保留的基础日志。

---

## 16. 多模型扩展

新模型作为新的 profile 接入，不替换既有 profile。dense、sparse、rerank 分别通过各自接口扩展，Store 只关心向量维度、字段结构、索引类型和过滤能力是否匹配。

索引规则：

- 不在同一个 collection 里混用不同 dense 向量维度。
- 不在 dense-only collection 里直接写入 vector sparse。
- 代码不会在启动时阻止使用已有 app collection；切换模型、sparse 类型或向量库结构后，由配置和 app collection 重建流程保证索引不混用。
- 测试用例使用测试 collection 或临时目录，不复用生产 collection。

---

## 17. 部署

后端启动只依赖一个配置入口：

```text
CONFIG_FILE=/path/to/config.yaml
```

生产环境要求：

- 向量库使用独立持久化存储。
- 模型文件保存在固定路径。
- 配置文件由部署环境指定。
- 健康检查表示后端进程存活；就绪检查表示 RAG 组件和向量库已初始化完成。
- 该设计对应 Kubernetes 的 liveness/readiness 模式：健康检查可作为 liveness probe，就绪检查可作为 readiness probe。
- RAG 未 ready 时，写入、查询、文档列表等业务入口返回 503；后台初始化成功后自动恢复。
- LangSmith tracing 由部署环境通过 `LANGSMITH_TRACING`、`LANGSMITH_API_KEY`、`LANGSMITH_PROJECT` 控制，不写入 yaml。
- 不同检索组合需要使用不同 profile，并重建对应 app collection 或 index。
- Qdrant、Chroma、Milvus 等具体服务按各自方式部署；服务型数据库和嵌入式文件库的部署边界要分开处理。
- 同名文件替换使用 document key 细粒度锁或按 document key 分区的写入队列。
- 向量库数据目录需要独立备份。

Docker 开发模式按计算资源拆分运行入口。GPU 声明使用 Docker Compose device reservation 写法：

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
```

GPU profile 的后端进程同时服务 API 和进程内索引消费器，模型只加载一份；并发与消费行为见 2.7。

Docker Compose 默认设置 `TZ=Asia/Shanghai`，对外展示时间和日志时间会按该时区输出。存储层仍保存 UTC 时间；部署到其他时区时通过外部 `TZ` 环境变量覆盖展示时区。

数据目录按数据库产品分组。服务型数据库由独立进程持有数据目录；嵌入式文件库由后端进程直接读写，不要同时启动多个后端访问同一份嵌入式库文件。


---

# 多节点监控聚合与集中日志架构

## 部署拓扑

RAG backend 支持多节点部署。Nginx 只承担统一入口和负载均衡，不再为每个节点维护独立的 `/nodes/...` 路由。

```mermaid
flowchart LR
  Browser["浏览器 / 上游系统"] --> Nginx["Nginx 统一入口"]
  Nginx -->|"/api/open/rag/*"| RagBackends["rag upstream"]
  Nginx -->|"/api/open/llm/*"| LlmBackends["llm upstream"]
  RagBackends --> B1["rag node-233"]
  RagBackends --> B2["rag node-90"]
  LlmBackends --> L1["llm node-233"]
  LlmBackends --> L2["llm node-90"]
  B1 -->|Loki HTTP API| Loki["Loki"]
  B2 -->|Loki HTTP API| Loki
  P1["Promtail node-233"] --> Loki
  P2["Promtail node-90"] --> Loki
  B1 -. fan-out .-> B2
  B2 -. fan-out .-> B1
```

统一入口：

- `/api/open/rag/*`：转发到 `rag` upstream，由 Nginx 负载均衡。
- `/api/open/llm/*`：转发到 `llm` upstream，由 Nginx 负载均衡。
- `/`：读取 nginx 容器内的前端静态文件。

RAG 节点端口固定为宿主端口 `6000`。当前静态 upstream 包含：

- `19.16.1.233:6000`
- `19.16.1.90:6000`

## 节点聚合

节点列表由环境变量提供：

| 变量 | 说明 |
|---|---|
| `RAG_NODE_ID` | 当前 backend 节点 ID |
| `RAG_PEERS` | 全部 backend 节点 base_url，逗号分隔，包含自身 |

单节点接口保留：

- `GET /api/open/rag/monitor`
- `GET /api/open/rag/config`

聚合接口由任意一个 backend 节点执行 fan-out：

- `GET /api/open/rag/nodes/monitor`
- `GET /api/open/rag/nodes/config`

聚合接口并发请求 `RAG_PEERS` 中所有节点，透传调用方的 User JWT。单个节点超时、连接失败或返回非 200 时，该节点标记为 `unreachable`，不会拖垮整体响应。

返回结构：

```json
{
  "nodes": [
    {
      "node_id": "node-233",
      "base_url": "http://19.16.1.233:6000",
      "status": "ok",
      "latency_ms": 12.4,
      "data": {},
      "error": null
    }
  ],
  "generated_at": "2026-08-21T12:00:00+08:00"
}
```

`status` 只有两个值：

- `ok`：节点响应正常，`data` 是对应单节点接口返回。
- `unreachable`：节点不可达，`data=null`，`error` 保存原因。

`/api/open/rag/monitor` 和 `/api/open/rag/config` 顶层都包含 `node_id`，作为聚合展示和配置漂移判断的基础字段。

## 前端监控

前端不再保存 backend API 节点地址，也不再提供节点切换下拉。

监控页读取：

```text
GET /api/open/rag/nodes/monitor
```

页面按节点并列展示：

- 节点 ID
- 节点地址
- 节点状态
- 响应耗时
- 当前 profile
- Store / Dense / Sparse / Rerank / OCR / database 组件状态

配置页读取：

```text
GET /api/open/rag/nodes/config
```

页面按节点并列展示当前配置，并以第一个正常节点为基准做轻量配置漂移判断。漂移判断忽略 `node_id`，其余配置不同则标记为配置不一致。

## 集中日志

应用日志仍输出 JSONL 到 stdout，Docker 使用 `json-file` driver 做小容量本地滚动保留。集中日志由 Promtail 采集 Docker stdout 并推送到 Loki。

每个节点运行一个 Promtail：

- 读取本机 Docker 容器日志。
- 只采集带 `logging=loki` label 的容器。
- 写入 Loki 时附带 `node_id`、`container`、`stream`、`level` label。

Loki 只在主节点启用，其他节点的 Promtail 通过 `LOKI_URL` 推送到主节点 Loki。Loki 不可用只影响集中日志查询，不影响 RAG 检索、索引和本地 Docker 日志。

Loki 日志保留 30 天。Docker 本地日志只作为 Promtail 采集来源和节点本地排障兜底，不作为长期日志存储。

日志页和链路页通过后端按时间范围查询 Loki：

```text
GET /api/open/rag/logs
GET /api/open/rag/logs/labels/container
GET /api/open/rag/traces
```

日志页支持按节点、容器和时间范围过滤。链路页查询 `rag.trace` 的 `search_trace` 结构化日志，按当前 app 和时间范围过滤并展示各阶段耗时。日志和链路列表使用 Loki 时间游标继续加载：首次查询当前时间范围内最新一批记录，继续加载时把上一批最早记录前一纳秒作为下一次查询的 `end`。

## 鉴权边界

管理台仍使用 User JWT。节点聚合请求 fan-out 到 peer 节点时，原样透传调用方 `Authorization: Bearer ...`。

管理台日志和链路请求进入后端，后端完成 User JWT 校验后查询 Loki。

上游业务接口仍使用 AK/SK 签名，路径保持 `/api/open/rag/*`。多节点监控和 Loki 日志是管理台能力，不改变上游业务 API 契约。

## 配置与数据目录

`deploy/.env.example` 是版本化配置模板；每个部署节点复制为对应环境目录下的 `.env` 后再按节点修改。Docker 部署读取 `deploy/cpu/.env`、`deploy/gpu/.env` 或 `deploy/ecu/.env`。

共享依赖节点示例：

```dotenv
RAG_NODE_ID=node-233
RAG_PEERS=http://19.16.1.233:6000,http://19.16.1.90:6000
DATABASE_URL=postgresql://rag:rag@19.16.1.233:5432/rag
QDRANT_URL=http://19.16.1.233:6333
S3_ENDPOINT_URL=http://19.16.1.233:9000
LOKI_URL=http://19.16.1.233:3100
```

应用节点示例：

```dotenv
CONFIG_FILE=rag/config/qdrant-bgebase.yaml
RAG_NODE_ID=node-90
RAG_PEERS=http://19.16.1.233:6000,http://19.16.1.90:6000
DATABASE_URL=postgresql://rag:rag@19.16.1.233:5432/rag
QDRANT_URL=http://19.16.1.233:6333
S3_ENDPOINT_URL=http://19.16.1.233:9000
LOKI_URL=http://19.16.1.233:3100
```

这些依赖地址必须指向 deps 所在节点，可以是任意服务器 IP 或域名。GPU 节点使用 `deploy/gpu/.env`，并把 `CONFIG_FILE` 配为 `rag/config/qdrant-bgem3-rerank.yaml`。

新增数据目录：

```text
loki_data/
```

该目录保存 Loki 本地数据，不入 Git。

## 运行约束

svc compose 运行共享依赖；rag compose 运行同构应用节点。所有 rag 节点都运行 backend、frontend、nginx 和 Promtail。rag 节点通过对应环境目录 `.env` 里的 `DATABASE_URL`、`QDRANT_URL`、`S3_ENDPOINT_URL`、`LOKI_URL` 显式连接依赖节点。

节点拓扑由环境变量静态配置。新增或删除节点需要更新各节点环境 `.env` 中的 `RAG_PEERS`，然后重启 backend / nginx / promtail 相关服务。

Loki 为单实例部署。主节点不可用时，集中日志查询不可用；各节点本地 Docker `json-file` 日志仍可通过宿主机查看。
