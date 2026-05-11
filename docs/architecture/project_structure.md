# Project Structure

This document contains the current project structure. It keeps only the directory skeleton and core files, omitting runtime/cache directories such as `.git`, `.venv`, `.pytest_cache`, `.ruff_cache`, and `__pycache__`.

```text
toLink-Rag/                         # 仓库根目录
├── .agents/                      # Agent/Skill 配置
│   └── skills/                   # 项目专用 Agent 技能
│       ├── agents-tree-sync/     # AGENTS.md 目录树同步规则
│       ├── auto-test/            # 自动化测试生成工作流
│       ├── code-annotator/       # 代码注释生成工作流
│       ├── code-review-and-quality/ # 代码审查与质量门禁
│       ├── contract-guard/       # 跨模块公共契约校验
│       ├── doc-maintenance-sync/ # 项目文档同步维护规则
│       ├── implementation-execution/ # 需求实现执行流程
│       ├── mq-middleware/        # MQ 中台开发规范
│       ├── mysql-ddl-conventions/ # MySQL DDL 规范
│       ├── prd-generator/        # PRD 生成工作流
│       ├── pre-prd-requirement-analysis/ # 需求预分析工作流
│       ├── run-all-tests/        # 全量测试运行工作流
│       ├── skill-optimizer/      # 既有 Skill 优化工作流
│       ├── swagger-annotation/   # Swagger 注解生成工作流
│       ├── tdd/                  # 测试驱动开发工作流
│       └── technical-design/     # 技术设计生成工作流
├── .env.example                  # 环境变量样例
├── AGENTS.md                     # 项目级 Agent 说明
├── README.md                     # 项目说明
├── docker-compose.yml            # 本地依赖编排
├── project_info.md               # 项目基础信息
├── pyproject.toml                # Python 依赖与项目配置
├── configs/                      # 本地评估和运行配置
│   └── eval/                     # 解析评估 Pipeline YAML
│       └── parser_opendataloader_only.yaml
├── scripts/                      # 可执行脚本
│   ├── db/                       # 数据库初始化脚本
│   │   ├── init.sql              # 当前数据库表结构（DDL）
│   │   └── schema.sql            # 初始化数据脚本
├── src/                          # 应用源码
│   ├── config.py                 # 全局配置
│   ├── database.py               # 数据库初始化入口
│   ├── main.py                   # FastAPI 应用入口
│   ├── api/                      # HTTP API 分层
│   │   ├── routes/               # 路由层
│   │   │   ├── internal.py       # 内部 LLM 配置/用量查询接口
│   │   │   ├── llm.py
│   │   │   ├── mq.py
│   │   │   └── parse.py
│   │   └── schemas/              # HTTP 请求/响应模型
│   │       ├── mq.py
│   │       └── parse.py
│   ├── cache/                    # 缓存客户端与缓存基础设施
│   │   ├── cache_manager.py      # CacheBackend / CacheManager 抽象
│   │   └── redis_client.py       # Redis 客户端
│   ├── core/                     # 核心能力与基础设施
│   │   ├── database.py
│   │   ├── exceptions.py
│   │   ├── es_index_storage/     # 文件级 Elasticsearch 入库阶段
│   │   │   ├── models.py
│   │   │   └── pipeline.py
│   │   ├── llm/                  # LLM 抽象、工厂与厂商适配
│   │   │   ├── factory.py
│   │   │   ├── interfaces.py
│   │   │   └── providers/        # LLM 提供方实现
│   │   ├── pipeline/             # 文档解析业务流水线编排
│   │   │   ├── constants.py       # 解析任务状态、通知文案等流水线常量
│   │   │   ├── error_codes.py
│   │   │   ├── models.py
│   │   │   ├── parse_task_pipeline.py
│   │   │   ├── post_process_constants.py
│   │   │   └── post_process_repository.py
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
│   │   │   ├── rule_chunker.py
│   │   │   └── semantic_chunker.py
│   │   ├── chunk_fact_storage/   # Chunk SQL 事实存储
│   │   │   ├── constants.py
│   │   │   ├── exceptions.py
│   │   │   ├── models.py
│   │   │   └── repository.py
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
│   ├── evaluation/               # 解析质量评估模块
│   │   ├── cli.py                # 评估 CLI 入口
│   │   ├── config.py             # 评估配置
│   │   ├── contracts/            # 评估协议与共享数据结构
│   │   ├── adapters/             # 被评估对象适配层
│   │   ├── datasets/             # 数据集加载与 manifest 解析
│   │   ├── evaluators/           # 评估器与对比逻辑
│   │   ├── hooks/                # 日志与进度 Hook
│   │   ├── metrics/              # Parser / Chunker 指标实现
│   │   ├── reporters/            # JSON / Markdown 报告输出
│   │   ├── runners/              # Pipeline 校验与评估编排
│   │   └── storage/              # 评估结果持久化
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
│       ├── file_downloader.py
│       ├── logger.py
│       └── text_formatter.py
└── tests/                        # 测试目录
    ├── README.md                 # pytest 统一入口（marker/集成测试开关）
    ├── conftest.py               # 测试分层与运行约定
    ├── evaluation_datasets/      # 评估模块内置数据集与 manifest
    │   ├── parser_smoke/
    │   └── chunker_smoke/
    ├── unit/                     # 单元测试 (Mock 驱动)
    │   ├── api/                  # API 层单元测试
    │   ├── core/                 # 核心模块单元测试
    │   │   ├── es_index_storage/ # ES 入库阶段单元测试
    │   │   ├── llm/              # LLM 模块单元测试
    │   │   ├── mq/               # MQ 模块单元测试
    │   │   ├── parser/           # 解析器模块单元测试
    │   │   ├── chunk_fact_storage/ # Chunk 事实存储单元测试
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
        │   ├── mq/               # MQ 解析流水线集成测试
        │   ├── qdrant_vector_storage/ # Qdrant 存储集成测试
        │   ├── splitter/         # 切分模块集成测试
        │   └── vector_storage/   # 向量存储编排集成测试
        ├── services/             # 服务层集成测试
        └── test_connectivity.py
```
