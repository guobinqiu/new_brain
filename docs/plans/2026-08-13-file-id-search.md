# File ID 检索重构执行计划

**目标：** 系统使用单一 `knowledge_chunks` collection 存储所有 chunk。外部系统保存自己的文件和 RAG `file_id` 的映射关系，搜索时可传多个 `file_id` 限定检索范围；不传 `file_ids` 表示全量搜索。

**最终架构：** 文件列表、文件计数、删除、搜索过滤都基于向量库 chunk metadata 完成。上传接口返回对象存储地址；对象存储索引接口同步完成解析、OCR、embedding 和写入向量库后返回 `file_id`。

**技术栈：** FastAPI、dependency-injector、LangChain、Qdrant、Chroma、Milvus、MinIO、pytest、Vue/Vite。

## 全局约束

- `/api/index` 可接收上游传入的 `file_id`；不传时由 RAG 生成 32 位 hex ID。
- 同一个 `file_id` 再次写入时，写入前删除旧 chunks，再插入新 chunks。
- `file_id` 是唯一搜索范围字段。
- 单次搜索最多接收 1000 个 `file_id`。
- 向量库统一使用 `collections.chunks`。
- chunk metadata 保存必要字段：`file_id`、`chunk_index`、`filename`、`s3_url`。
- `file_id` 是过滤字段；Qdrant 和 Milvus 必须为它建立过滤索引，Chroma local 使用 metadata filter 和本地内置 metadata 索引能力。
- MinIO 只用于 Docker 开发环境模拟 S3 行为；生产环境由上游系统提供可下载的 `presigned_url` 和稳定的 `s3_url`。

## 数据模型

### 向量库 collection

```text
collection: knowledge_chunks
chunk 主键: 各向量库自己的 point id / primary key / document id
content: chunk 文本
vector: dense vector / 可选 vector sparse
metadata:
  file_id
  chunk_index
  filename
  s3_url
```

### metadata 索引

| 字段 | 是否建索引 | 用途 |
|---|---|---|
| `file_id` | 是 | 搜索范围过滤，`file_id in (...)` |
| `chunk_index` | 否 | 展示、排查、后续上下文扩展 |
| `filename` | 否 | 搜索结果展示和文件列表聚合 |
| `s3_url` | 否 | 对象存储来源追溯 |

## API 终态

### 上传本地文件到对象存储

```http
POST /api/upload
Content-Type: multipart/form-data
```

请求字段：

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

接口返回时，文件已经写入对象存储；该接口不写入向量库。

### 签名对象存储文件

```http
POST /api/presign
Content-Type: application/json
```

请求字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `s3_url` | string | 是 | 稳定对象存储地址，例如 `s3://bucket/key` |
| `expires_in` | int | 否 | 签名有效期，单位秒 |

响应：

```json
{
  "presigned_url": "http://minio:9000/rag-dev/uploads/example.pdf?..."
}
```

这个接口服务本地 MinIO 场景。生产环境如果需要重新获取原文，由业务系统根据自己保存的 `s3_url` 或对象 key 重签，再调用 RAG 的 `/api/index`。

### 索引对象存储文件

```http
POST /api/index
Content-Type: application/json
```

请求字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file_id` | string | 否 | 上游文件 ID；传了会覆盖该 `file_id` 的旧 chunks，不传则由 RAG 生成 |
| `presigned_url` | string | 是 | 本次索引用的一次性下载 URL，不写入 metadata |
| `s3_url` | string | 是 | 稳定对象存储地址，例如 `s3://bucket/key`，写入 metadata 用于追溯 |
| `filename` | string | 否 | 自定义展示文件名；不传时从 `s3_url` 推导 |

请求示例：

```json
{
  "file_id": "upstream-file-001",
  "presigned_url": "https://example.com/presigned",
  "s3_url": "s3://bucket/path/to/example.pdf"
}
```

响应：

```json
{
  "file_id": "upstream-file-001"
}
```

`presigned_url` 只用于本次下载。`file_id` 推荐由上游系统保存映射关系；不传时由 RAG 生成。

### 文件聚合列表

```http
GET /api/files?limit=50&cursor=...
```

响应：

```json
{
  "files": [
    {
      "id": "upstream-file-001",
      "filename": "example.pdf",
      "chunk_count": 12
    }
  ],
  "next_cursor": "50",
  "has_more": true
}
```

`/api/files` 是前端内部接口，从向量库 metadata 聚合文件级信息。

### 向量数据列表

```http
GET /api/chunks?limit=50&cursor=...
```

响应：

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

`/api/chunks` 是前端内部接口，直接分页查看向量库里的 chunk 数据。

### 搜索

```http
POST /api/search
Content-Type: application/json
```

请求示例：

```json
{
  "query": "有多少华为卡",
  "mode": "hybrid",
  "sparse_mode": "app",
  "top_k": 20,
  "rerank": true,
  "fetch_k": 50,
  "dense_weight": 0.5,
  "sparse_weight": 0.5,
  "rrf_k": 60,
  "file_ids": ["upstream-file-001"]
}
```

规则：

- 不传 `file_ids`：全量搜索。
- 传非空 `file_ids`：只搜索这些文件。
- 传 `file_ids: []`：返回 400，错误信息为 `file_ids cannot be empty`。
- 超过 1000 个 `file_id`：返回 400，错误信息为 `file_ids exceeds max limit: 1000`。

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

删除直接按 `file_id` 删除向量库里的 chunks。

## 写入流程

### 本地上传

```text
1. API 接收 multipart 文件
2. 文件写入对象存储
3. API 返回 s3_url + filename
4. 调用 /api/presign 获取 presigned_url
5. 调用 /api/index 执行对象存储索引流程
```

### 对象存储索引

```text
1. API 接收 presigned_url, s3_url，可选 filename
2. 使用请求里的 file_id；没有传则由 RAG 生成 file_id
3. 使用 presigned_url 下载文件到临时路径
4. DocumentParser 解析、OCR、切 chunk
5. 每个 chunk 写入 metadata: file_id, chunk_index, filename, s3_url
6. Store 写入向量库
7. API 返回 file_id
8. 临时文件可清理
```

## Store 能力

```python
class Store:
    def add_file_chunks(self, chunks: list[dict], file_id: str) -> int: ...
    def delete_file_chunks(self, file_id: str) -> int: ...
    def list_files(self, limit: int = 50, cursor: str | None = None) -> FilePage: ...
    def count_files(self) -> int: ...
    def get_total_chunks(self, file_ids: list[str] | None = None) -> int: ...
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
```

`list_files()` 从 chunk metadata 聚合得到文件列表，同一个 `file_id` 下的 chunks 聚合成一条文件记录。`chunk_count` 是该 `file_id` 对应 chunk 数。

## 向量库要求

### Qdrant

- `metadata.file_id` 创建 payload index。
- 过滤条件使用 `metadata.file_id in file_ids`。
- `chunk_index`、`filename` 不建 payload index。

### Milvus

- `file_id` 使用 schema scalar field，类型为 `VARCHAR`。
- `chunk_index`、`filename` 会随每条 chunk 一起保存，搜索结果可以返回这些字段。
- `chunk_index`、`filename` 不作为搜索过滤条件，不建索引。
- collection 创建后为 `file_id` 创建 scalar index。
- 过滤条件使用 `file_id in [...]`。

### Chroma local

- `file_id` 写入 metadata。
- 查询使用 `where={"file_id": {"$in": file_ids}}`。
- Chroma local 会把 metadata 写入内部 SQLite metadata 表，并有通用 `(key, string_value)` 索引；本项目不创建 `file_id` 专用索引。

## MinIO 开发环境

Docker CPU/GPU 开发环境都包含 MinIO：

```text
service: minio
api: http://localhost:19000
console: http://localhost:19001
bucket: rag-dev
```

后端连接 MinIO 的配置通过环境变量提供：

```text
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
S3_BUCKET=rag-dev
```

本地联调路径：

```text
1. 前端调用 /api/upload，把文件上传到 MinIO bucket
2. /api/upload 返回 s3_url + filename
3. 前端调用 /api/presign 获取 presigned_url
4. 前端调用 /api/index，传 presigned_url + s3_url
5. RAG 下载、解析、写入向量库并返回 file_id
```

## 查询监控

`/api/search` 不返回 trace。后端把最近若干次搜索 trace 写入内存 ring buffer，`/api/monitor` 或独立内部接口供前端监控页读取。

trace 表格字段使用一层结构：

```text
total_ms
prepare_ms
dense_ms
sparse_ms
fusion_ms
dedupe_ms
rerank_ms
format_ms
```

长期日志仍走 JSONL logging；监控页只展示运行中最近记录。

## 前端终态

- 搜索区保留 file_ids 文本框，英文逗号分隔；留空表示全量搜索。
- 文件列表使用 infinite scroll，展示 `filename`、`file_id`、`chunk_count`。
- 文件列表不提供“填入”按钮。
- 监控页显示组件状态、模型名、存储位置、文件数、chunk 数、最近搜索 trace 表格。
- 配置页先保留入口，不在第一阶段修改 store/dense/vector sparse 这类会改变索引结构的配置。

## Benchmark 终态

- benchmark 数据写入固定 `file_id`。
- 搜索 benchmark 使用 `file_ids=[file_id]`。
- 报告列保留：

```text
database
dense
sparse
sparse_impl
mode
rerank
top_k
target_rank
```

## 验收

- `/api/upload` 成功返回 `s3_url` 和 `filename`。
- `/api/index` 成功返回基于 `s3_url` 生成的 `file_id`。
- `/api/files` 从向量库聚合文件列表。
- `/api/search` 不传 `file_ids` 时全量搜索，传非空 `file_ids` 时限定范围。
- Qdrant/Milvus 的 `file_id` 过滤索引存在。
- Docker CPU/GPU 环境能启动 MinIO，并能通过本地 presign 接口跑通 `/api/index`。
- 单元测试、e2e 测试和前端 build 通过。

## 风险点

- 这是索引结构变更，旧 collection 数据不能直接复用，需要重建索引。
- 文件列表来自向量库 metadata 聚合，超大数据量下需要继续评估分页和聚合成本。
- Chroma local 只能使用 metadata filter 和内置 metadata 索引能力，不能像 Qdrant/Milvus 一样显式创建 `file_id` 专用索引。
- 同步索引会让上传请求耗时变长；如果后续要支撑高并发上传，再把写入流程迁移到独立 worker 或对象存储事件队列。
