# ContentStore 架构演进计划

**目标：** 把 chunk 正文存储从向量库 Store 中拆出，形成可配置的 `ContentStore`。向量库负责检索索引，ContentStore 负责 chunk 正文、文件信息和状态数据。

**当前模式：** chunk 正文随向量一起写入向量库。Qdrant 使用 payload `content`，Chroma 使用 `documents`，Milvus 使用 scalar 字段 `text`。

**目标模式：** 支持 `vector` 和 `postgres` 两种 ContentStore 后端。默认可以继续使用 `vector`；生产环境可以使用 `postgres`，让 Postgres 做事实表，向量库只做检索索引。

## 配置

```yaml
content_store:
  type: vector
```

`vector` 表示 chunk 正文保存在向量库里。向量库保存 vector、chunk 文本和 metadata。

```yaml
content_store:
  type: postgres
  dsn: postgresql://rag:rag@postgres:5432/rag
```

`postgres` 表示 chunk 正文保存在 Postgres。向量库只保存 vector、`chunk_id`、`file_id`、`chunk_index` 等检索必要字段。

## 数据职责

| 数据 | `vector` 模式 | `postgres` 模式 |
|---|---|---|
| chunk 正文 | 向量库 | Postgres |
| dense vector | 向量库 | 向量库 |
| vector sparse | 向量库 | 向量库 |
| `file_id` 过滤字段 | 向量库 metadata/scalar | 向量库 metadata/scalar + Postgres |
| `chunk_id` | 向量库主键 | Postgres 主键 + 向量库引用 |
| 文件列表 | 从向量库 metadata 聚合 | 从 Postgres 查询 |
| 文件状态 | 不保存 | Postgres |

## Postgres 表结构

```sql
create table files (
  id text primary key,
  filename text not null,
  s3_url text,
  status text not null
);

create table chunks (
  id text primary key,
  file_id text not null references files(id),
  chunk_index integer not null,
  content text not null
);
```

`files.id` 使用 RAG 生成的 `file_id`。`chunks.id` 使用 RAG 生成的 `chunk_id`，并作为向量库里的引用字段。

## 写入流程

```text
1. API 接收本地文件或 presigned_url + s3_url
2. RAG 生成 file_id
3. DocumentParser 解析、OCR、切 chunk
4. ContentStore 写入 files 和 chunks
5. VectorStore 写入 chunk_id、file_id、chunk_index 和 vector
6. API 返回 file_id
```

`postgres` 模式下，向量库不保存 chunk 正文；搜索结果正文从 Postgres 回表获取。

## 查询流程

```text
1. VectorStore 按 query + file_id filter 搜索
2. VectorStore 返回 chunk_id、file_id、chunk_index、score
3. ContentStore 按 chunk_id 批量读取 content 和文件信息
4. SearchPipeline 合并 score、content、metadata
5. rerank 和 format_response 使用合并后的结果
```

## 接口边界

```python
class ContentStore:
    def add_file_chunks(self, file_id: str, filename: str, chunks: list[dict], s3_url: str | None = None) -> list[dict]: ...
    def get_chunks(self, chunk_ids: list[str]) -> dict[str, dict]: ...
    def delete_file(self, file_id: str) -> int: ...
    def list_files(self, limit: int = 50, cursor: str | None = None) -> FilePage: ...
    def count_files(self) -> int: ...
```

```python
class VectorStore:
    def add_chunk_vectors(self, chunks: list[dict]) -> int: ...
    def delete_file_vectors(self, file_id: str) -> int: ...
    def search_dense(self, query: str, limit: int, metadata_filter: object) -> list[dict]: ...
    def search_sparse(self, query: str, limit: int, metadata_filter: object) -> list[dict]: ...
```

`ContentStore.add_file_chunks()` 返回带 `chunk_id` 的 chunks，供 VectorStore 写入引用。

## 迁移约束

`vector` 和 `postgres` 两种模式不能直接切配置复用同一份旧数据：

- `vector -> postgres`：需要把向量库里的 chunk 正文迁移到 Postgres，或重新索引原始文件。
- `postgres -> vector`：需要把 Postgres chunk 正文重新写入向量库，或重新索引原始文件。
- 切换模式时必须重建或迁移向量库索引，保证 `chunk_id`、`file_id` 和正文来源一致。

## 风险点

- 查询会多一次 Postgres 回表。
- 写入需要维护 Postgres 和向量库的一致性。
- 删除需要同时删除 ContentStore 和 VectorStore。
- 异步索引、失败重试、状态流转需要围绕 ContentStore 设计。
