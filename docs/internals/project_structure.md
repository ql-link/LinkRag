# Project Structure

This document contains the current project structure. It keeps only the directory skeleton and core files, omitting runtime/cache directories such as `.git`, `.venv`, `.pytest_cache`, `.ruff_cache`, and `__pycache__`.

```text
toLink-Rag/                         # 仓库根目录
├── .agents/                      # Agent/Skill 配置
│   └── skills/                   # 项目专用 Agent 技能
│       ├── agents-tree-sync/     # AGENTS.md 目录树同步规则
│       ├── auto-test/            # 自动化测试生成工作流
│       ├── branch-pr-workflow/   # dev 分支交付收口与 PR 创建工作流
│       ├── code-annotator/       # 代码注释生成工作流
│       ├── code-review-and-quality/ # 代码审查与质量门禁
│       ├── contract-guard/       # 跨模块公共契约校验
│       ├── doc-maintenance-sync/ # 项目文档同步维护规则
│       ├── implementation-execution/ # 需求实现执行流程
│       ├── mq-middleware/        # MQ 中台开发规范
│       ├── mysql-ddl-conventions/ # MySQL DDL 规范
│       ├── acceptance-generator/ # Gherkin 验收契约生成工作流（替代旧版 PRD）
│       ├── brief-generator/      # 需求 brief 生成工作流（替代旧版需求预分析）
│       ├── run-all-tests/        # 全量测试运行工作流
│       ├── skill-optimizer/      # 既有 Skill 优化工作流
│       ├── swagger-annotation/   # Swagger 注解生成工作流
│       ├── tdd/                  # 测试驱动开发工作流
│       └── technical-design/     # 技术设计生成工作流
├── .env.example                  # 环境变量样例
├── AGENTS.md                     # 项目级 Agent 入口（与 CLAUDE.md 内容同步）
├── CLAUDE.md                     # 项目统一入口：使用说明 + 文档目录
├── README.md                     # 面向用户的项目介绍
├── docker-compose.yml            # 本地依赖编排
├── pyproject.toml                # Python 依赖与项目配置
├── docs/                         # 项目文档（按读者旅程组织）
│   ├── README.md                 # 一页索引
│   ├── api/                      # 对外契约：HTTP / MQ / Schema / 错误码
│   │   ├── http_contracts.md
│   │   ├── mq_contracts.md
│   │   ├── error_codes.md
│   │   └── schemas/              # MySQL / Qdrant / Elasticsearch
│   ├── internals/                # 内部实现：模块、约定
│   │   ├── project_structure.md
│   │   ├── pipeline_architecture.md
│   │   ├── parse_task_pipeline.md
│   │   ├── recall_pipeline.md
│   │   ├── recall_http_api.md
│   │   ├── file_parser.md
│   │   ├── markdown_parser.md
│   │   ├── chunking.md
│   │   ├── vectorization.md
│   │   ├── sparse_vector.md
│   │   ├── preprocessor.md
│   │   ├── es_index_storage.md
│   │   ├── mq.md
│   │   ├── llm.md
│   │   ├── cache.md
│   │   ├── object_storage.md
│   │   └── naming_conventions.md
│   ├── ops/                      # 部署与配置
│   │   ├── deploy.md
│   │   └── configure.md
│   └── contributing.md           # 分支/提交/测试/迁移/文档同步
├── alembic.ini                   # Alembic 配置入口
├── migrations/                   # Alembic 数据库迁移
│   ├── env.py                    # 运行环境：DB URL + 合并 Base.metadata
│   ├── script.py.mako            # 迁移文件模板
│   ├── db.sql                    # 0001 baseline 冻结快照（DDL，冷启动用；禁止改动）
│   └── versions/                 # 版本化迁移脚本（NNNN_YYYYMMDD_slug.py）
├── scripts/                      # 可执行脚本
│   ├── db/                       # 数据库初始化脚本
│   │   ├── init.sql              # 叠加全部 migration 后的当前完整结构快照（仅供查阅）
│   │   └── schema.sql            # 初始化数据脚本
├── src/                          # 应用源码
│   ├── config.py                 # 全局配置
│   ├── database.py               # 数据库初始化入口
│   ├── main.py                   # FastAPI 应用入口
│   ├── nltk_bootstrap.py         # NLTK 数据路径引导（项目内 nltk_data 优先）
│   ├── api/                      # HTTP API 分层
│   │   ├── internal_auth.py       # Java 管理端内部接口鉴权
│   │   ├── recall_session_auth.py # 召回会话鉴权
│   │   ├── recall_pipeline_provider.py # 召回 Pipeline 装配/提供
│   │   ├── recall_stream_runtime.py    # 召回流式运行时
│   │   ├── routes/               # 路由层
│   │   │   ├── internal.py        # Java 管理端内部 LLM 配置/用量接口
│   │   │   ├── llm.py
│   │   │   ├── mq.py
│   │   │   ├── parse.py
│   │   │   ├── rag.py             # 对外 RAG 问答流 SSE 入口
│   │   │   └── recall.py          # 对外纯召回 JSON 入口
│   │   └── schemas/              # HTTP 请求/响应模型
│   │       ├── mq.py
│   │       └── parse.py
│   ├── cache/                    # 缓存客户端与缓存基础设施
│   │   ├── redis_client.py       # 异步 Redis 连接单例
│   │   └── cache_manager.py      # CacheManager + 后端抽象（Redis / Null）
│   ├── core/                     # 核心能力与基础设施
│   │   ├── database.py
│   │   ├── llm/                  # LLM 抽象、工厂与厂商适配
│   │   │   ├── factory.py
│   │   │   ├── interfaces.py
│   │   │   ├── base_provider.py
│   │   │   ├── circuit_breaker.py  # 厂商调用熔断
│   │   │   ├── encryption.py       # 用户密钥加解密
│   │   │   ├── exceptions.py
│   │   │   ├── response.py
│   │   │   ├── tokenizer.py
│   │   │   ├── user_model_resolver.py # 用户模型选择解析
│   │   │   └── providers/        # LLM 提供方实现（openai/anthropic/qwen/glm/deepseek）
│   │   ├── pipeline/             # 业务流水线编排
│   │   │   ├── parse_task/        # 解析任务主编排
│   │   │   │   ├── pipeline.py     # ParseTaskPipeline 薄编排（分流/幂等/校验/重试）
│   │   │   │   ├── constants.py    # 解析任务状态、通知文案等流水线常量
│   │   │   │   ├── error_codes.py
│   │   │   │   ├── models.py
│   │   │   │   ├── log_repository.py / source.py / notifier.py / validator.py / temp_workspace.py / _utils.py
│   │   │   │   ├── stages/         # 类化阶段编排（base/context/services + cleaning/chunking/
│   │   │   │   │                   #   vectorizing/sparse_vectorizing/pretokenize/es_indexing）
│   │   │   │   └── post_process/   # 文件级后处理状态机（constants/models/repository）
│   │   │   └── recall/            # 多路召回 Pipeline（pipeline/models/protocols/fusion/exceptions）
│   │   ├── preprocessor/         # ES 预分词：RAGFlow 分词 → FilePostIndexPlan
│   │   │   ├── service.py         # Preprocessor：读 chunk 构建预分词计划
│   │   │   ├── ragflow_tokenizer.py # RagFlowTokenizer 适配
│   │   │   └── models.py          # FileIndexMeta / ChunkWithTokens / FilePostIndexPlan
│   │   ├── sparse_vector/        # BGE-M3 稀疏向量编码与索引
│   │   │   ├── encoder.py / http_encoder.py / remote_encoder.py # 本地 / 远程编码器
│   │   │   ├── factory.py         # 按 provider 装配 SparseVectorService
│   │   │   ├── pipeline.py        # SparseVectorService 服务接口
│   │   │   ├── indexing.py        # SparseIndexingPipeline 文件级索引阶段
│   │   │   ├── sparse_retriever.py # 召回 Pipeline 适配器
│   │   │   ├── deploy_bge_m3.py   # 本地模型部署/冒烟脚本
│   │   │   └── constants.py / models.py / exceptions.py
│   │   ├── prompts/              # LLM 提示词模板
│   │   │   └── markdown_enhancement.py
│   │   ├── markdown_parser/      # Markdown 解析与增强编排
│   │   │   ├── image_extractor.py
│   │   │   ├── llm_integration.py
│   │   │   ├── models.py
│   │   │   ├── orchestrator.py
│   │   │   ├── parser.py
│   │   │   ├── provider_clients.py
│   │   │   └── scanner.py
│   │   ├── mq/                   # MQ 中台核心实现
│   │   │   ├── factory.py        # MQFactory
│   │   │   ├── interfaces.py
│   │   │   ├── message.py        # AbstractMessage / MessagePayload
│   │   │   ├── exceptions.py
│   │   │   ├── retry.py          # 消费重试策略
│   │   │   ├── topic_admin.py    # Topic 初始化逻辑
│   │   │   ├── consumers/        # MQ 消费者
│   │   │   │   └── parse_task_consumer.py
│   │   │   ├── messages/         # MQ 业务消息
│   │   │   │   ├── parse_task.py
│   │   │   │   ├── parse_result.py
│   │   │   │   ├── cache_sync.py
│   │   │   │   └── usage_report.py
│   │   │   └── vendors/          # MQ 厂商适配
│   │   │       ├── rabbitmq_adapter.py
│   │   │       └── kafka/        # Kafka 适配与 Topic 管理
│   │   │           ├── kafka_adapter.py
│   │   │           └── topic_admin.py
│   │   ├── parser/               # 文档解析器抽象与实现
│   │   │   ├── base.py
│   │   │   ├── factory.py
│   │   │   ├── html/             # HTML DOM 解析、表格处理和图片引用重写
│   │   │   │   ├── image_rewriter.py
│   │   │   │   ├── models.py
│   │   │   │   ├── renderer.py
│   │   │   │   ├── service.py
│   │   │   │   └── table_processor.py
│   │   │   ├── pdf/              # PDF 解析服务与后端
│   │   │   │   ├── base.py
│   │   │   │   ├── models.py
│   │   │   │   ├── registry.py    # PDF 解析后端注册表
│   │   │   │   ├── service.py
│   │   │   │   └── backends/     # PDF 解析后端实现
│   │   │   │       ├── mineru_backend.py
│   │   │   │       ├── opendataloader_backend.py
│   │   │   │       └── naive_backend.py
│   │   │   └── providers/        # 多格式解析器实现
│   │   │       ├── html_parser.py
│   │   │       ├── pdf_parser.py
│   │   │       └── word_parser.py
│   │   ├── splitter/             # 文本切分与嵌入流水线
│   │   │   ├── base.py
│   │   │   ├── chunking_engine.py
│   │   │   ├── embedding_pipeline.py
│   │   │   ├── models.py
│   │   │   ├── pipeline_chunker.py
│   │   │   └── semantic_chunker.py
│   │   ├── chunk_fact_storage/   # Chunk SQL 事实存储
│   │   │   ├── constants.py
│   │   │   ├── exceptions.py
│   │   │   ├── models.py
│   │   │   └── repository.py
│   │   ├── es_index_storage/      # ES 入库 + BM25 检索
│   │   │   ├── client.py          # 进程级 AsyncElasticsearch 单例
│   │   │   ├── mapping.py         # ES index settings + mappings
│   │   │   ├── document_factory.py / batcher.py # chunk → bulk action / 分批
│   │   │   ├── pipeline.py        # EsIndexingPipeline 入库阶段
│   │   │   ├── retrieval.py       # EsBm25Retriever BM25 检索
│   │   │   ├── bm25_retriever.py  # 召回 Pipeline 适配器
│   │   │   ├── retrieval_models.py # Bm25RecallRequest / Bm25ChunkHit
│   │   │   ├── smoke.py           # 集成测试冒烟工具
│   │   │   └── models.py / exceptions.py
│   │   ├── qdrant_vector_storage/ # Qdrant 向量索引存储
│   │   │   ├── bucket_router.py
│   │   │   ├── constants.py
│   │   │   ├── exceptions.py
│   │   │   ├── models.py
│   │   │   ├── point_factory.py
│   │   │   └── qdrant_store.py
│   │   └── vector_storage/       # 向量存储编排层
│   │       ├── compensation_pipeline.py
│   │       ├── constants.py
│   │       ├── draft_factory.py
│   │       ├── exceptions.py
│   │       ├── facade.py
│   │       ├── factory.py
│   │       ├── management_pipeline.py
│   │       ├── models.py
│   │       ├── pipeline.py
│   │       ├── repair_policy.py
│   │       └── _transaction.py
│   ├── models/                   # ORM 模型
│   │   ├── chunk_record.py
│   │   ├── db_models.py
│   │   ├── parse_task.py
│   │   ├── system_provider.py
│   │   ├── usage_log.py
│   │   └── user_llm_config.py
│   ├── services/                 # 服务层
│   │   ├── mq_service.py
│   │   ├── parse_task_service.py
│   │   ├── cache_sync_service.py
│   │   ├── config_reader_service.py
│   │   ├── usage_log_service.py
│   │   └── storage/              # 对象存储抽象与实现
│   │       ├── base.py
│   │       ├── factory.py
│   │       ├── minio_storage.py
│   │       └── oss_storage.py
│   └── utils/                    # 通用工具函数
│       ├── logger.py
│       └── text_formatter.py
└── tests/                        # 测试目录
    ├── README.md                 # pytest 统一入口（marker/集成测试开关）
    ├── conftest.py               # 测试分层与运行约定
    ├── unit/                     # 单元测试 (Mock 驱动)
    │   ├── api/                  # API 层单元测试
    │   ├── core/                 # 核心模块单元测试
    │   │   ├── llm/              # LLM 模块单元测试
    │   │   ├── mq/               # MQ 模块单元测试
    │   │   ├── parser/           # 解析器模块单元测试
    │   │   ├── chunk_fact_storage/ # Chunk 事实存储单元测试
    │   │   ├── es_index_storage/ # ES 入库阶段单元测试
    │   │   ├── pipeline/         # 解析流水线单元测试
    │   │   ├── qdrant_vector_storage/ # Qdrant 存储单元测试
    │   │   ├── splitter/         # 切分模块单元测试
    │   │   └── vector_storage/   # 向量存储编排单元测试
    │   └── services/             # 服务层单元测试
    └── integration/              # 集成测试
        ├── api/                  # API 层集成测试
        ├── core/                 # 核心模块集成测试
        │   ├── llm/              # LLM 模块集成测试
        │   ├── markdown_parser/  # Markdown 解析集成测试
        │   ├── qdrant_vector_storage/ # Qdrant 存储集成测试
        │   ├── splitter/         # 切分模块集成测试
        │   └── vector_storage/   # 向量存储编排集成测试
        ├── services/             # 服务层集成测试
        └── test_connectivity.py
```
