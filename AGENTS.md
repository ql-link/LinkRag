# AGENTS

## 项目概览

- 项目名称：`toLink-Rag`
- 技术栈：`FastAPI`、`SQLAlchemy`、`Redis`、`MySQL`、`MinIO`、`Qdrant`、`Kafka/RabbitMQ`
- Python 版本：`3.10+`
- 默认虚拟环境：仓库根目录下的 `.venv`
- 应用入口：[src/main.py](src/main.py)

## 目录约定

- [src/api/routes](src/api/routes)：FastAPI 路由层
- [src/api/schemas](src/api/schemas)：HTTP 请求/响应模型
- [src/services](src/services)：服务层
- [src/core](src/core)：核心能力与基础设施
- [src/core/mq](src/core/mq)：MQ 中台
- [src/core/pipeline](src/core/pipeline)：解析任务业务流水线
- [src/core/vector_storage](src/core/vector_storage)：向量存储与 Chunk 管理
- [src/models](src/models)：ORM 模型
- [tests/unit](tests/unit)：单元测试
- [tests/integration](tests/integration)：集成测试与真实基础设施测试
- [scripts](scripts)：可执行脚本
- [docs](docs)：设计和说明文档

当前项目结构如下（仅保留目录骨架和核心文件，已省略 `.git`、`.venv`、`.pytest_cache`、`.ruff_cache`、`__pycache__` 等运行时/缓存目录）：

```text
toLink-Rag/
├── .agents/                      # Agent/Skill 配置
│   └── skills/
│       ├── agents-tree-sync/
│       ├── auto-test/
│       ├── mq-middleware/
│       ├── mysql-ddl-conventions/
│       ├── prd-generator/
│       ├── swagger-annotation/
│       └── tdd/
├── .env.example                  # 环境变量样例
├── AGENTS.md                     # 项目级 Agent 说明
├── README.md                     # 项目说明
├── pyproject.toml                # Python 依赖与项目配置
├── docs/                         # 设计与说明文档
├── scripts/                      # 可执行脚本
│   ├── db/
│   │   ├── init.sql              # 建库建表脚本
│   │   └── schema.sql            # 初始化数据脚本
│   ├── init_kafka_topics.py      # Kafka Topic 初始化（Python Admin API）
│   └── init_kafka_topics.sh      # Kafka Topic 初始化（CLI）
├── src/                          # 应用源码
│   ├── config.py                 # 全局配置
│   ├── database.py               # 数据库初始化入口
│   ├── main.py                   # FastAPI 应用入口
│   ├── api/
│   │   ├── routes/               # 路由层
│   │   │   ├── llm.py
│   │   │   ├── mq.py
│   │   │   └── parse.py
│   │   └── schemas/              # HTTP 请求/响应模型
│   │       ├── mq.py
│   │       └── parse.py
│   ├── cache/
│   │   └── redis_client.py       # Redis 客户端
│   ├── core/                     # 核心能力与基础设施
│   │   ├── database.py
│   │   ├── llm/
│   │   │   ├── factory.py
│   │   │   ├── interfaces.py
│   │   │   └── providers/
│   │   ├── pipeline/             # 文档解析业务流水线编排
│   │   │   ├── models.py
│   │   │   └── parse_task_pipeline.py
│   │   ├── markdown_parser/
│   │   │   ├── image_extractor.py
│   │   │   ├── llm_integration.py
│   │   │   ├── models.py
│   │   │   ├── orchestrator.py
│   │   │   ├── parser.py
│   │   │   ├── provider_clients.py
│   │   │   └── scanner.py
│   │   ├── mq/
│   │   │   ├── factory.py        # MQFactory
│   │   │   ├── interfaces.py
│   │   │   ├── message.py        # AbstractMessage / MessagePayload
│   │   │   ├── topic_admin.py    # Topic 初始化逻辑
│   │   │   ├── consumers/
│   │   │   │   └── parse_task_consumer.py
│   │   │   ├── messages/         # MQ 业务消息
│   │   │   │   ├── parse_task.py
│   │   │   │   ├── cache_sync.py
│   │   │   │   └── usage_report.py
│   │   │   └── vendors/
│   │   │       ├── rabbitmq_adapter.py
│   │   │       └── kafka/
│   │   │           ├── kafka_adapter.py
│   │   │           └── topic_admin.py
│   │   ├── parser/
│   │   │   ├── base.py
│   │   │   ├── factory.py
│   │   │   ├── pdf/
│   │   │   │   ├── base.py
│   │   │   │   ├── models.py
│   │   │   │   ├── service.py
│   │   │   │   └── backends/
│   │   │   │       ├── mineru_backend.py
│   │   │   │       └── naive_backend.py
│   │   │   └── providers/
│   │   │       ├── html_parser.py
│   │   │       ├── pdf_parser.py
│   │   │       └── word_parser.py
│   │   ├── splitter/
│   │   │   ├── base.py
│   │   │   ├── chunking_engine.py
│   │   │   ├── embedding_pipeline.py
│   │   │   ├── models.py
│   │   │   ├── pipeline_chunker.py
│   │   │   ├── rule_chunker.py
│   │   │   └── semantic_chunker.py
│   │   └── vector_storage/       # 向量存储与 Chunk 管理
│   │       ├── bucket_router.py
│   │       ├── constants.py
│   │       ├── draft_factory.py
│   │       ├── exceptions.py
│   │       ├── facade.py
│   │       ├── factory.py
│   │       ├── models.py
│   │       ├── point_factory.py
│   │       ├── services/
│   │       │   ├── base.py
│   │       │   ├── compensation.py
│   │       │   ├── management.py
│   │       │   └── storage.py
│   │       └── stores/
│   │           ├── qdrant_store.py
│   │           └── repository.py
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
│   │   └── storage/
│   │       ├── base.py
│   │       ├── factory.py
│   │       ├── minio_storage.py
│   │       └── oss_storage.py
│   └── utils/
│       ├── file_downloader.py
│       ├── logger.py
│       └── text_formatter.py
└── tests/                        # 测试目录
    ├── README.md                 # pytest 统一入口（marker/集成测试开关）
    ├── conftest.py               # 测试分层与运行约定
    ├── unit/                     # 单元测试 (Mock 驱动)
    │   ├── api/
    │   ├── core/
    │   │   ├── llm/
    │   │   ├── mq/
    │   │   ├── parser/
    │   │   ├── pipeline/
    │   │   ├── splitter/
    │   │   └── vector_storage/
    │   └── services/
    └── integration/              # 集成测试
        ├── api/
        ├── core/
        │   ├── llm/
        │   ├── markdown_parser/
        │   ├── splitter/
        │   └── vector_storage/
        ├── services/
        └── test_connectivity.py
```

## 配置约定

- 所有运行时配置统一从 [src/config.py](src/config.py) 的 `Settings` 读取。
- 本地环境变量样例参考 [.env.example](.env.example)。
- 不要硬编码敏感信息；新增配置时同步更新 `Settings` 和 `.env.example`。

## 工作方式

- 先读现有结构，再落代码，不基于想象扩目录。
- 优先做与当前仓库约定一致的最小改动。
- 涉及 MQ、配置、启动流程、脚本目录时，以本文件和 `mq-middleware` skill 为准。