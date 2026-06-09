# Documentation

按读者旅程组织。先想清楚"我是谁、我要做什么"，再选目录。

## 我是谁

| 你的角色 | 看这里 |
| --- | --- |
| **对接方 / 业务方**：调 HTTP API、收 MQ 消息、读写共享数据库 | [api/](api/) |
| **内部开发者**：改代码、看模块边界、加新模块 | [internals/](internals/) |
| **运维 / 部署方**：起服务、调配置、看依赖 | [ops/](ops/) |
| **贡献者**：提 PR、跑测试、写迁移、走 spec-as-test 流程 | [contributing.md](contributing.md) |
| **AI Agent / 新成员**：从 0 理解项目 | [../CLAUDE.md](../CLAUDE.md) |

## 目录速览

### [api/](api/) — 对外契约

| 文件 | 内容 |
| --- | --- |
| [http_contracts.md](api/http_contracts.md) | REST API 接口契约 |
| [mq_contracts.md](api/mq_contracts.md) | MQ 消息载荷与对接说明 |
| [error_codes.md](api/error_codes.md) | 业务错误码 |
| [schemas/mysql.md](api/schemas/mysql.md) | MySQL 表结构（共 12 张表） |
| [schemas/qdrant.md](api/schemas/qdrant.md) | Qdrant collection 与 payload |
| [schemas/elasticsearch.md](api/schemas/elasticsearch.md) | ES 索引结构 |

### [internals/](internals/) — 内部实现

| 文件 | 内容 |
| --- | --- |
| [project_structure.md](internals/project_structure.md) | 项目目录结构 |
| [pipeline_architecture.md](internals/pipeline_architecture.md) | 解析 Pipeline 架构 |
| [parse_task_pipeline.md](internals/parse_task_pipeline.md) | 解析任务流水线状态机 |
| [recall_pipeline.md](internals/recall_pipeline.md) | 召回 Pipeline 架构 |
| [recall_generation.md](internals/recall_generation.md) | 召回后 RAG 答案生成（正文回填/上下文拼装/流式生成） |
| [recall_http_api.md](internals/recall_http_api.md) | 召回 HTTP 入口与会话/鉴权 |
| [file_parser.md](internals/file_parser.md) | 文件解析器（含回退链） |
| [markdown_parser.md](internals/markdown_parser.md) | Markdown 解析与 LLM 增强 |
| [chunking.md](internals/chunking.md) | 分块策略与流水线 |
| [vectorization.md](internals/vectorization.md) | 向量化模块（dense） |
| [sparse_vector.md](internals/sparse_vector.md) | 稀疏向量（BGE-M3）编码与索引 |
| [preprocessor.md](internals/preprocessor.md) | ES 预分词（RAGFlow） |
| [es_index_storage.md](internals/es_index_storage.md) | ES 索引与 BM25 检索 |
| [chunk_fact_storage.md](internals/chunk_fact_storage.md) | Chunk SQL 事实存储（真值源/状态机） |
| [mq.md](internals/mq.md) | MQ 中间件实现 |
| [llm.md](internals/llm.md) | LLM 调用模块 |
| [cache.md](internals/cache.md) | 缓存基础设施（Redis） |
| [object_storage.md](internals/object_storage.md) | 对象存储 |
| [naming_conventions.md](internals/naming_conventions.md) | 命名约定 |

### [ops/](ops/) — 部署与配置

| 文件 | 内容 |
| --- | --- |
| [deploy.md](ops/deploy.md) | 部署指南 |
| [configure.md](ops/configure.md) | 配置详解 |

### [contributing.md](contributing.md) — 贡献者规范

涵盖分支、提交、代码风格、测试、Alembic 迁移、文档同步、spec-as-test 工作流。

## 文档体系约定

- 每个事实**只在一处**正式描述，其他位置用链接引用。
- 文档是代码的摘要，代码是权威源。冲突时**改文档不改代码**。
- 临时交付物（PRD、技术方案、实施报告）放 [.specs/](../.specs/)，不进 docs/。
- 修改文档前阅读 [contributing.md §七](contributing.md#七文档体系约定修改-docs-前必读)。
