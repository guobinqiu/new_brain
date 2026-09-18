# 知识库

## 安装

```
单节点本地

  1. 初始化 Swarm：

     docker swarm init

  2. 登录镜像仓库：

     docker login --username=guobin2019 crpi-70lgf6bn1vq8bydf.cn-hangzhou.personal.cr.aliyuncs.com

  3. 构建并推送服务镜像：

     just ops build && just ops push
     just rag build && just rag push
     just parser build && just parser push
     just inference build && just inference push
     just llm build && just llm push

  4. 构建前端：

     just webui build

  5. 启动管理入口：

     just ctrl up

  6. 打开管理台：

     http://localhost:5175

  7. 在管理台“部署”页点“发布”，创建业务和基础服务
  8. 在管理台“服务”页启动/停止/扩缩容服务

  多节点新增机器

  1. 在管理台“节点”页复制 worker 或 manager join 命令
  2. 到新机器执行 join 命令
  3. 新机器准备同路径代码和模型目录，因为当前服务还有 bind mount：

     /Users/guobin/workspace/new_brain  # 本机路径示例

     生产建议统一成类似：

     /srv/new_brain

  4. 需要跑本地模型、TEI、vLLM 或 parser 本地模型的节点，准备 models 目录：

     scripts/download_models.txt 里有模型下载命令

  5. GPU 节点打标签：

     docker node update --label-add gpu=true <node-name>

     GPU 节点需要安装 NVIDIA Container Toolkit，并保证容器可以访问 GPU

  6. 新机器不需要 build 镜像；Swarm 会从阿里云镜像仓库拉
  7. 如果代码没有打进镜像，所有节点要保持 Git 代码版本一致。
  8. TEI/vLLM 已在 deploy/deploy.yaml 中注册为 Swarm service，默认副本数为 0，需要时在管理台“基础服务”里启动

```

## API

Base URL 示例：

```
http://localhost:5175
```

公共请求头：

| 字段          | 必填 | 说明                   |
| ------------- | ---- | ---------------------- |
| Authorization | 是   | `Bearer <app_api_key>` |
| Content-Type  | 是   | `application/json`     |

### 创建单文件索引

```
POST /api/v1/rag/files
```

用于把一个已经上传到对象存储的文件写入知识库。`presigned_url` 可以直接传；如果不传，RAG 会按当前应用的 S3 预签名配置重新获取下载地址。

请求字段：

| 字段          | 类型   | 必填 | 说明                                                        |
| ------------- | ------ | ---- | ----------------------------------------------------------- |
| file_id       | string | 否   | 文件 ID；不传时由 RAG 生成，建议上游传入以便失败后幂等重试  |
| s3_url        | string | 是   | 文件对象地址，必须以 `s3://` 开头                           |
| filename      | string | 否   | 原始文件名；不传时从 `s3_url` 推导                          |
| presigned_url | string | 否   | 文件下载 URL；不传时使用应用的预签名配置生成                |
| app_id        | string | 否   | 管理接口兼容字段；开放接口使用 API Key 绑定的应用，一般不传 |

成功响应字段：

| 字段      | 类型    | 说明              |
| --------- | ------- | ----------------- |
| success   | boolean | 固定为 `true`     |
| error     | null    | 成功时为空        |
| retryable | boolean | 固定为 `false`    |
| traceId   | string  | 本次请求 trace ID |
| file_id   | string  | 文件 ID           |

失败响应字段：

| 字段      | 类型    | 说明                     |
| --------- | ------- | ------------------------ |
| success   | boolean | 固定为 `false`           |
| error     | string  | 原始错误信息             |
| retryable | boolean | 当前错误是否建议上游重试 |
| traceId   | string  | 本次请求 trace ID        |
| file_id   | string  | 文件 ID                  |

状态码：

| 状态码 | 说明                                         |
| ------ | -------------------------------------------- |
| 200    | 索引创建成功                                 |
| 400    | 参数错误、文件类型不支持、未配置预签名信息等 |
| 401    | 未传或无效的 `Authorization`                 |
| 409    | 文件正在索引中等状态冲突                     |
| 422    | 请求体字段校验失败                           |
| 429    | 触发限流                                     |
| 500    | 服务内部错误                                 |
| 503    | 下游服务不可用、超时或依赖未就绪             |

请求示例：

```bash
curl -X POST http://localhost:5175/api/v1/rag/files \
  -H 'Authorization: Bearer <app_api_key>' \
  -H 'Content-Type: application/json' \
  -d '{
    "file_id": "file-001",
    "s3_url": "s3://rag/uploads/imsdom/file-001/demo.pdf",
    "filename": "demo.pdf"
  }'
```

成功示例：

```json
{
  "success": true,
  "error": null,
  "retryable": false,
  "traceId": "8fbf6f4f7d5146b7a3b0eaa2bb84fb6c",
  "file_id": "file-001"
}
```

失败示例：

```json
{
  "success": false,
  "error": "parser returned HTTP 503",
  "retryable": true,
  "traceId": "7c4909520441497e9aa26aa258c76f31",
  "file_id": "file-001"
}
```

### 批量创建索引

```
POST /api/v1/rag/files/batch
```

用于一次提交多个文件索引任务。该接口只是批量壳，内部逐个调用 `POST /api/v1/rag/files`；任意文件失败时，顶层 `success=false`，每个文件的结果保留单文件接口原始响应。

请求字段：

| 字段            | 类型    | 必填 | 说明                                                                        |
| --------------- | ------- | ---- | --------------------------------------------------------------------------- |
| files           | array   | 是   | 文件列表，默认最多 10 个                                                    |
| max_concurrency | integer | 否   | 本次请求并发数，上限由 `rag.yaml` 的 `api.batch_index.max_concurrency` 控制 |

`files[]` 字段：

| 字段          | 类型   | 必填 | 说明                                         |
| ------------- | ------ | ---- | -------------------------------------------- |
| file_id       | string | 是   | 文件 ID；批量接口要求上游显式传入            |
| s3_url        | string | 是   | 文件对象地址，必须以 `s3://` 开头            |
| filename      | string | 否   | 原始文件名                                   |
| presigned_url | string | 否   | 文件下载 URL；不传时使用应用的预签名配置生成 |

响应字段：

| 字段    | 类型    | 说明                                                |
| ------- | ------- | --------------------------------------------------- |
| success | boolean | 所有文件都成功时为 `true`；任意文件失败时为 `false` |
| files   | array   | 每个文件的索引结果，结构与单文件接口一致            |

状态码：

| 状态码 | 说明                                                                |
| ------ | ------------------------------------------------------------------- |
| 200    | 批量请求已执行完成；是否有单文件失败看响应体 `success` 和 `files[]` |
| 401    | 未传或无效的 `Authorization`                                        |
| 422    | 请求体字段校验失败、文件数量超过限制                                |
| 429    | 触发限流                                                            |
| 500    | 批量调度内部错误                                                    |
| 503    | 批量调度依赖不可用或超时                                            |

请求示例：

```bash
curl -X POST http://localhost:5175/api/v1/rag/files/batch \
  -H 'Authorization: Bearer <app_api_key>' \
  -H 'Content-Type: application/json' \
  -d '{
    "max_concurrency": 3,
    "files": [
      {
        "file_id": "file-001",
        "s3_url": "s3://rag/uploads/imsdom/file-001/a.pdf",
        "filename": "a.pdf"
      },
      {
        "file_id": "file-002",
        "s3_url": "s3://rag/uploads/imsdom/file-002/b.docx",
        "filename": "b.docx"
      }
    ]
  }'
```

成功示例：

```json
{
  "success": true,
  "files": [
    {
      "success": true,
      "error": null,
      "retryable": false,
      "traceId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "file_id": "file-001"
    },
    {
      "success": true,
      "error": null,
      "retryable": false,
      "traceId": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "file_id": "file-002"
    }
  ]
}
```

部分失败示例：

```json
{
  "success": false,
  "files": [
    {
      "success": true,
      "error": null,
      "retryable": false,
      "traceId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "file_id": "file-001"
    },
    {
      "success": false,
      "error": "inference returned HTTP 503",
      "retryable": true,
      "traceId": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "file_id": "file-002"
    }
  ]
}
```

### 搜索

```
POST /api/v1/rag/search
```

用于从当前应用知识库检索相关 chunk。开放接口使用 API Key 绑定的应用，不需要传 `app_id`。

请求字段：

| 字段           | 类型     | 必填 | 说明                                                          |
| -------------- | -------- | ---- | ------------------------------------------------------------- |
| query          | string   | 是   | 查询文本                                                      |
| mode           | string   | 否   | `dense`、`sparse`、`hybrid`；不传使用配置默认值               |
| top_k          | integer  | 否   | 返回数量，范围 1 到 50                                        |
| rerank         | boolean  | 否   | 是否启用重排；不传使用配置默认值                              |
| rerank_fetch_k | integer  | 否   | 重排前召回数量，范围 1 到 100；启用重排时必须大于等于 `top_k` |
| rrf_k          | integer  | 否   | Hybrid RRF 参数，范围 1 到 1000                               |
| file_ids       | string[] | 否   | 限定检索文件，最多 1000 个                                    |
| app_id         | string   | 否   | 管理接口兼容字段；开放接口一般不传                            |

响应字段：

| 字段           | 类型            | 说明                                                      |
| -------------- | --------------- | --------------------------------------------------------- |
| results        | array           | 检索结果列表                                              |
| mode           | string          | 实际检索模式；`hybrid` 在 sparse 不可用时会降级为 `dense` |
| rerank         | boolean         | 本次是否启用重排                                          |
| rerank_fetch_k | integer 或 null | 重排前召回数量；未启用重排时为 `null`                     |
| elapsed_ms     | number          | 检索耗时，单位毫秒                                        |

`results[]` 字段：

| 字段    | 类型   | 说明           |
| ------- | ------ | -------------- |
| id      | string | chunk ID       |
| content | string | chunk 文本内容 |
| score   | number | 检索得分       |

状态码：

| 状态码 | 说明                             |
| ------ | -------------------------------- |
| 200    | 搜索成功                         |
| 400    | 参数错误、sparse/rerank 未配置等 |
| 401    | 未传或无效的 `Authorization`     |
| 422    | 请求体字段校验失败               |
| 429    | 触发限流                         |
| 500    | 服务内部错误                     |
| 503    | inference、向量库等依赖不可用    |

请求示例：

```bash
curl -X POST http://localhost:5175/api/v1/rag/search \
  -H 'Authorization: Bearer <app_api_key>' \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "代位权",
    "mode": "hybrid",
    "top_k": 3,
    "rerank": true,
    "rerank_fetch_k": 20
  }'
```

成功示例：

```json
{
  "results": [
    {
      "id": "d65fc085-051f-5b90-b2ce-73ee00000001",
      "content": "如果债务人怠于行使自己已经到期的权利...",
      "score": 0.4209124445915222
    }
  ],
  "mode": "hybrid",
  "rerank": true,
  "rerank_fetch_k": 20,
  "elapsed_ms": 1134.2
}
```

失败示例：

```json
{
  "error": "sparse search is not configured",
  "retryable": false,
  "traceId": "94f8f2dab8a2400587153d69912bea48"
}
```

### 删除文件索引

```
DELETE /api/v1/rag/files/{file_id}
```

用于删除当前应用下某个文件的向量索引。开放接口根据 API Key 识别应用，不需要传 `app_id`。

路径参数：

| 字段    | 类型   | 必填 | 说明    |
| ------- | ------ | ---- | ------- |
| file_id | string | 是   | 文件 ID |

响应字段：

| 字段           | 类型    | 说明                |
| -------------- | ------- | ------------------- |
| deleted_chunks | integer | 已删除的 chunk 数量 |

状态码：

| 状态码 | 说明                                              |
| ------ | ------------------------------------------------- |
| 200    | 删除完成；`deleted_chunks=0` 表示没有匹配到 chunk |
| 401    | 未传或无效的 `Authorization`                      |
| 429    | 触发限流                                          |
| 500    | 服务内部错误                                      |
| 503    | 向量库不可用                                      |

请求示例：

```bash
curl -X DELETE http://localhost:5175/api/v1/rag/files/file-001 \
  -H 'Authorization: Bearer <app_api_key>'
```

成功示例：

```json
{
  "deleted_chunks": 28
}
```

失败示例：

```json
{
  "error": "Fail connecting to vector database",
  "retryable": true,
  "traceId": "d93fc7e6fe3541cb96c1f7e421c12eea"
}
```
