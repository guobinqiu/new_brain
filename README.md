# 知识库

## 安装

```
单节点本地

  1. 初始化 Swarm：

     docker swarm init

  2. 登录镜像仓库：

     docker login --username=guobin2019 crpi-70lgf6bn1vq8bydf.cn-hangzhou.personal.cr.aliyuncs.com

  3. 构建并推送服务镜像：

     just build ops && just push ops
     just build rag && just push rag
     just build parser && just push parser
     just build inference && just push inference
     just build llm && just push llm

  4. 打包前端静态文件：

     just bundle webui

  5. 启动管理入口：

     just ctrl up

  6. 打开管理台：

     http://localhost:5175

  7. 在管理台“部署”页先选择“基础服务”发布，待所需基础服务就绪，再选择“应用服务”发布
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
  8. TEI/vLLM 已在 deploy/infra.yaml 中注册为 Swarm service，默认副本数为 0，需要时在管理台“基础服务”里启动

```

## 命令

在项目根目录执行以下命令：

| 命令格式 | 示例 | 作用 |
| --- | --- | --- |
| `just ctrl up` | `just ctrl up` | 部署管理入口 |
| `just ctrl down` | `just ctrl down` | 删除管理入口 stack |
| `just infra up` | `just infra up` | 部署基础服务 stack |
| `just infra down` | `just infra down` | 删除基础服务 stack，不删除磁盘数据 |
| `just deploy up` | `just deploy up` | 只部署应用服务 stack |
| `just deploy down` | `just deploy down` | 删除应用服务 stack |
| `just build <服务名>` | `just build rag` | 构建服务镜像 |
| `just bundle <服务名>` | `just bundle webui` | 打包前端静态文件 |
| `just push <服务名>` | `just push rag` | 推送该服务的镜像 |
| `just service start <Swarm服务名>` | `just service start brain_rag` | 将服务副本数设为 1 |
| `just service stop <Swarm服务名>` | `just service stop brain_rag` | 将服务副本数设为 0 |
| `just service rollout <Swarm服务名>` | `just service rollout brain_rag` | 强制滚动更新服务 |
| `just service remove <Swarm服务名>` | `just service remove brain_rag` | 删除服务 |
| `just --list` | `just --list` | 查看命令入口 |

部署文件与 stack 对应关系：

| 文件 | Stack | 服务 |
| --- | --- | --- |
| `deploy/ctrl.yaml` | `brain_ctrl` | Ops、Nginx |
| `deploy/infra.yaml` | `brain_infra` | PostgreSQL、MinIO、向量库、日志、TEI、vLLM |
| `deploy/deploy.yaml` | `brain` | RAG、Parser、Inference、LLM |

三个 stack 共用外部 overlay 网络 `brain-net`，服务间仍用 `postgres`、`minio`、`parser` 等 DNS 名连接。
首次命令行部署顺序为 `just ctrl up`、`just infra up`、`just deploy up`；日常发布应用只执行 `just deploy up`。
修改共用的 `deploy/.env` 后，分别发布受影响的 stack。`down` 不删除绑定目录的数据，也不删除外部网络。

### 从合并部署迁移

旧部署的基础服务仍属于 `brain` stack；发布新文件不会自动删除它们。迁移需要维护窗口：

1. 备份数据，记录服务副本数及所在节点，停止应用请求。
2. 列出旧基础服务：`docker service ls --filter label=com.docker.stack.namespace=brain --filter label=group=infra`。
3. 对确认的旧基础服务逐个执行 `docker service rm <服务名>`，等待所在节点上的旧容器全部退出。不要删除数据目录。
4. 执行 `just infra up`，沿用同一个 `PROJECT_ROOT` 和数据目录；多节点需确保有状态服务仍调度到原数据节点。
5. 确认基础服务就绪后执行 `just deploy up`，恢复应用请求。

迁移前不要执行 `just deploy down`，它会删除旧 `brain` stack 中尚未迁走的基础服务。不要同时运行两套指向同一数据目录的数据库。

各服务的构建、推送示例：

| 服务 | 构建 | 推送镜像 |
| --- | --- | --- |
| rag | `just build rag` | `just push rag` |
| parser | `just build parser` | `just push parser` |
| inference | `just build inference` | `just push inference` |
| llm | `just build llm` | `just push llm` |
| ops | `just build ops` | `just push ops` |
| webui | `just bundle webui` | 无需推送镜像 |

`just service` 的服务名填写 `docker service ls` 显示的实际名称，会原样传给 Docker，不自动添加前缀。

`just bundle webui` 执行 `npm --prefix webui run build`，生成前端静态文件，不生成镜像。

镜像地址由 `deploy/.env` 中的 `IMAGE_REGISTRY` 和 `IMAGE_TAG` 统一生成。
例如 `IMAGE_REGISTRY=registry.example.com/brain`、`IMAGE_TAG=amd64-gpu` 时，`just push rag` 会推送 `registry.example.com/brain/brain-rag:amd64-gpu`。
所有服务镜像统一使用 `deploy/Dockerfile` 构建，target 为服务名，例如 `just build llm`。
`USE_CN_MIRROR` 和 `SERVICE_EXTRA` 作为构建参数统一传给 Docker，由 Dockerfile 中的 `ARG` 声明决定是否使用。

## MinerU 本地解析

`services/parser/config/parser.yaml` 的 `parser.mineru` 使用 MinerU 4.0.3 Python SDK，仅处理 PDF，与 `mineru_cloud` 等其他 PDF provider 保持 `enable` 单选。现代 Office 仍使用原生解析；旧 `.doc/.xls/.ppt` 仍需选择 `mineru_cloud`。

```yaml
mineru:
  enable: true
  tier: basic # flash / basic / standard / advanced
  parse_method: auto # auto / ocr / txt
  image_analysis: false
```

`basic` 使用小模型，`standard` 和 `advanced` 还需要 VLM。`SERVICE_EXTRA=cpu` 安装基础依赖；Linux x86_64 的 `SERVICE_EXTRA=gpu` 额外安装 MinerU full/vLLM。GPU 运行还需要宿主机 NVIDIA 驱动、容器 GPU 访问权限，构建参数不会自动分配 GPU。

模型下载命令见 `scripts/download_models.txt`。使用 MinerU 4.0 官方 `mineru-kit models download` 和 `models verify`，模型根目录为项目 `models/mineru`（容器内 `/app/models/mineru`）；目录内部由工具管理，旧版 `mineru.json` 和 `pipeline/vlm` 模型不能替代 4.0 模型。

本地 provider 默认设置 `MINERU_MODEL_BASE_DIR` 为该目录、`MINERU_MODEL_SOURCE=local`，缺模型时不会自动联网下载。显式环境变量优先；其余引擎设置遵循 MinerU 官方 `$MINERU_HOME/config.yaml` / `MINERU_CONFIG` 和环境变量。下载和运行必须选择相同的 `MINERU_MODEL_SMALL_BACKEND`、`MINERU_MODEL_VLM_ENGINE`。MinerU 的 basic/standard/advanced 本地解析器在 Parser 启动时初始化模型，完成后才就绪，初始化失败会阻止启动；云端解析器不发送预热请求。MinerU flash 沿用官方行为，不预加载模型。部署前先执行 `models verify`。

新增依赖后需重新构建 Parser 镜像；当前配置启用本地 `mineru`，使用 `basic`，云端关闭。

### Linux NVIDIA GPU 使用 standard

以下命令在 GPU 机器的项目根目录执行。`standard` 使用 Torch 小模型和 vLLM，不能直接复用 CPU basic 下载的 ONNX 模型包。

1. 准备 GPU 运行环境。

   宿主机需要 NVIDIA 驱动和 NVIDIA Container Toolkit；Docker 需配置可供 Swarm 任务使用的 NVIDIA runtime（本部署方式使用 NVIDIA 作为默认 runtime）。仅设置 `SERVICE_EXTRA=gpu` 或 GPU 环境变量不会让容器自动获得 GPU。先确认宿主机 `nvidia-smi` 正常，并在 manager 上为目标节点添加调度标签：

   ```bash
   docker node update --label-add gpu=true <GPU节点名或ID>
   ```

2. 修改 `deploy/.env`，构建并推送 Parser 镜像。

   ```dotenv
   SERVICE_EXTRA=gpu
   IMAGE_TAG=amd64-gpu
   MINERU_MODEL_SMALL_BACKEND=torch
   MINERU_MODEL_VLM_ENGINE=vllm
   ```

   ```bash
   just build parser
   just push parser
   ```

   `IMAGE_TAG` 是所有应用镜像共用的标签。执行整套应用部署前，确认其他应用对应的 `amd64-gpu` 镜像也已存在于仓库。修改挂载的代码或应用配置后需 rollout；依赖变化仍需重新构建镜像，rollout 不会给旧镜像安装新依赖。

3. 下载并校验 standard 模型。

   ```bash
   export MINERU_MODEL_BASE_DIR="$PWD/models/mineru"

   uv run --project services/parser --python 3.11 --extra gpu mineru-kit models download --tier standard --small-backend torch --vlm-engine vllm --source modelscope
   uv run --project services/parser --python 3.11 --extra gpu mineru-kit models verify --tier standard --small-backend torch --vlm-engine vllm
   ```

   模型文件由官方工具放入 `models/mineru`。每个可调度 Parser 的 GPU 节点都需要准备相同挂载路径下的模型和代码；镜像推送不会分发宿主机的模型目录。不要把宿主机的 `MINERU_MODEL_BASE_DIR` 绝对路径写入容器环境，容器内默认使用 `/app/models/mineru`。

4. 修改解析配置，并补齐 Parser 的 GPU 部署设置。

   在 `services/parser/config/parser.yaml` 中启用 `parser.mineru`、设置 `tier: standard`，关闭其余 PDF provider。保留 `parse_method: auto` 和 `image_analysis: false` 即可。

   当前 `deploy/deploy.yaml` 的 `parser` 没有 GPU 环境变量和调度约束。将以下字段合并到现有 `parser` 配置，保留其他字段：

   ```yaml
   parser:
     environment:
       TZ: Asia/Shanghai
       NVIDIA_VISIBLE_DEVICES: all
       NVIDIA_DRIVER_CAPABILITIES: compute,utility
     deploy:
       placement:
         constraints:
           - node.labels.gpu == true
   ```

   `MINERU_MODEL_SMALL_BACKEND` 和 `MINERU_MODEL_VLM_ENGINE` 通过现有 `env_file: .env` 进入容器。`gpu=true` 只控制调度，不安装驱动，也不隔离多个服务之间的显存使用。

5. 部署并验证。

   ```bash
   just deploy up
   docker service ps brain_parser --no-trunc
   docker service logs --since 5m brain_parser
   ```

   在新 Parser 容器中执行 `nvidia-smi` 确认可见 GPU，再从前端提交 PDF 验证真实解析。模型在启动时初始化，`/ready` 成功仍不能代替真实文件的推理验证。修改 `.env` 或部署设置后需要重新部署，不是只做 rollout。

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
| service   | null    | 成功时为空        |
| retryable | boolean | 固定为 `false`    |
| traceId   | string  | 本次请求 trace ID |
| file_id   | string  | 文件 ID           |

失败响应字段：

| 字段      | 类型    | 说明                     |
| --------- | ------- | ------------------------ |
| success   | boolean | 固定为 `false`           |
| error     | string  | 原始错误信息             |
| service   | string  | 错误所属服务或组件，如 parser、inference、vector、database |
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
  "service": null,
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
  "service": "parser",
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
      "service": null,
      "retryable": false,
      "traceId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "file_id": "file-001"
    },
    {
      "success": true,
      "error": null,
      "service": null,
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
      "service": null,
      "retryable": false,
      "traceId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "file_id": "file-001"
    },
    {
      "success": false,
      "error": "inference returned HTTP 503",
      "service": "inference",
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
  "service": "rag",
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
  "service": "rag",
  "retryable": true,
  "traceId": "d93fc7e6fe3541cb96c1f7e421c12eea"
}
```
