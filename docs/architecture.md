# Brain 项目架构

## 服务关系

```mermaid
flowchart TB
    Client["WebUI / 上游系统"] --> Gateway["Nginx · 统一入口"]

    subgraph Business["业务服务"]
        RAG["RAG API · 索引与检索"]
        LLM["LLM · 会话与生成"]
    end

    Gateway --> RAG
    Gateway --> LLM
    LLM -->|知识检索| RAG
    RAG -->|文档解析| Parser["Parser"]
    RAG -->|向量化与重排| Inference["Inference"]
    LLM -->|生成| Model["语言模型服务"]

    subgraph Storage["持久化"]
        Object[("对象存储")]
        Vector[("向量数据库")]
        DB[("PostgreSQL")]
    end

    RAG -->|按调用方引用读取文件| Object
    RAG -->|检索索引| Vector
    RAG -.->|可选应用管理与文件状态| DB
    LLM -->|会话状态| DB
```

## WebUI 与 Nginx

WebUI 提供管理与交互入口，Nginx 托管前端并将请求分发到 RAG API 和 LLM 服务

文档管理与检索进入 RAG API，问答进入 LLM；Parser 和 Inference 由业务服务调用

## RAG API

以应用为数据隔离边界，核心负责鉴权、索引与检索；每个应用对应独立的向量集合。应用管理和文件状态持久化是可选能力

```mermaid
flowchart LR
    Key["App API Key"] --> Mode{"是否启用关系数据库"}
    Mode -->|否| Config["部署配置中的应用绑定"]
    Mode -->|是| DB["数据库中的应用凭据"]
    Config --> App["应用身份"]
    DB --> App
    App --> Scope["应用范围内索引与检索"]
```

鉴权来源由部署模式决定，数据库故障不回退到配置凭据

### 索引数据流

```mermaid
sequenceDiagram
    participant C as 调用方
    participant R as RAG API
    participant O as 调用方文件源
    participant P as Parser
    participant I as Inference
    participant V as 向量数据库
    participant D as PostgreSQL

    C->>R: 文件引用
    opt 启用关系数据库
        R->>D: 记录文件与索引状态
    end
    R->>O: 读取原始文件
    O-->>R: 文件内容
    R->>P: 解析文档
    P-->>R: 文档块
    R->>R: 切块、组装上下文、关联来源
    R->>I: 文本向量化
    I-->>R: 向量
    R->>V: 写入片段、向量与来源
    opt 启用关系数据库
        R->>D: 更新索引结果
    end
    R-->>C: 索引完成
```

索引在请求内同步完成，切块策略由 RAG API 管理。正文按段落独立分片，不合并不同段落；单段超长才依次按换行、句子和字符切分。表格仅以标题和完整行数据独立成片，不拼接前后文本。列表、代码和表格保留各自结构边界。直接读取调用方文件引用时，无需自建对象存储

索引链路不做整体重放。Parser、Inference 和 RAG 只在各自拥有的外部调用或写入边界内重试可恢复错误；达到上限后向调用方返回失败，由调用方用同一个 `file_id` 发起业务重试

### 检索数据流

```mermaid
sequenceDiagram
    participant C as 调用方
    participant R as RAG API
    participant I as Inference
    participant V as 向量数据库

    C->>R: 查询与文件范围
    R->>I: 查询向量化
    I-->>R: 查询向量
    R->>V: 在当前应用范围内召回
    V-->>R: 候选片段
    R->>R: 去重
    opt 启用重排
        R->>I: 查询与候选片段
        I-->>R: 相关性排序
    end
    R-->>C: 检索结果
```

## Parser

负责文件内容提取，通过统一文档块接口向 RAG API 交付解析结果，解析后端的差异保留在服务内部

```mermaid
flowchart TB
    File["文件"] --> Route{"按文档类型分流"}
    Route -->|文本与结构化文档| Native["原生读取"]
    Route -->|PDF| Select{"选择一个解析后端"}
    Select --> Ark["Volcengine · 方舟 API"]
    Select --> MP["MinerU 本地 · 4.0"]
    Select --> MV["MinerU Cloud"]
    Native --> Blocks["统一文档块"]
    MP --> Blocks
    MV --> Blocks
    Ark --> Blocks
    Blocks --> RAG["RAG API · 切块与索引"]
```

原生读取是 Parser 内部的公共能力，负责保留段落与表格结构，不生成检索分片。PDF 在本地解析后端与方舟之间选择一个，使用方舟仍运行 Parser 服务，但不加载本地 PDF 模型

## Inference

集中承载检索模型推理，向业务层提供两类独立能力

| 能力 | 输入 | 输出 | 使用阶段 |
| --- | --- | --- | --- |
| 向量化 | 文本 | 稠密向量、可选稀疏向量 | 索引、检索 |
| 重排 | 查询与候选片段 | 相关性排序 | 检索，可选 |

索引与查询必须使用一致的向量模型；重排只处理召回后的候选集

本地模型与外部供应商由 Inference 统一适配，RAG 只依赖服务接口及其能力声明

```mermaid
flowchart LR
    RAG["RAG API"] --> Inference["Inference · 统一推理接口"]
    Inference --> Local["本地模型"]
    Inference --> Cloud["SiliconFlow"]
```

模型、供应商与计算资源由 Inference 管理，与 RAG API 的业务编排独立部署

## LLM

每轮固定执行知识检索后再生成回答，当前消息用于检索，历史会话与检索结果共同组成生成上下文

```mermaid
flowchart LR
    Request["当前用户消息"] --> Retrieval["RAG API · 知识检索"]
    Request --> Context["组装生成上下文"]
    Retrieval -->|参考内容| Context
    Context --> Model["语言模型服务"]
    Model --> Answer["流式回答"]
    DB[("PostgreSQL")] -->|会话历史| Context
    Answer -->|会话检查点| DB
```

## 基础服务

| 服务 | 数据职责 | 访问方 |
| --- | --- | --- |
| PostgreSQL | 应用凭据、文件元数据与索引状态；会话状态 | RAG API、LLM 分别管理各自数据 |
| 对象存储 | 原始文件 | RAG API、上游系统 |
| 向量数据库 | 文档片段、向量与来源信息 | RAG API |
| Loki / Promtail | 日志汇集与查询 | 业务服务与管理台 |

向量数据库通过统一适配接口接入，Qdrant 与 Milvus 选择其一；对象存储采用 S3 兼容接口

各应用服务独立部署，共享持久化服务；跨服务调用传递同一追踪标识，用于关联解析、推理、检索和生成链路
