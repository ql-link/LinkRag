# AGENTS

## 项目概览

- 项目名称：`toLink-Rag`
- 技术栈：`FastAPI`、`SQLAlchemy`、`Redis`、`MySQL`、`MinIO`、`Qdrant`、`Kafka/RabbitMQ`
- Python 版本：`3.10+`
- 应用入口：[src/main.py](/Users/jixu/Project/Agent/toLink-Rag/src/main.py)

## 目录约定

- [src/api/routes](/Users/jixu/Project/Agent/toLink-Rag/src/api/routes)：FastAPI 路由层
- [src/api/schemas](/Users/jixu/Project/Agent/toLink-Rag/src/api/schemas)：HTTP 请求/响应模型
- [src/services](/Users/jixu/Project/Agent/toLink-Rag/src/services)：服务层
- [src/core](/Users/jixu/Project/Agent/toLink-Rag/src/core)：核心能力与基础设施
- [src/core/mq](/Users/jixu/Project/Agent/toLink-Rag/src/core/mq)：MQ 中台
- [src/models](/Users/jixu/Project/Agent/toLink-Rag/src/models)：ORM 模型
- [tests](/Users/jixu/Project/Agent/toLink-Rag/tests)：测试
- [scripts](/Users/jixu/Project/Agent/toLink-Rag/scripts)：可执行脚本
- [docs](/Users/jixu/Project/Agent/toLink-Rag/docs)：设计和说明文档

当前项目结构如下（仅保留目录骨架和核心文件，已省略 `.git`、`.venv`、`.pytest_cache`、`__pycache__` 等运行时/缓存目录）：

```text
toLink-Rag/
├── .agents/                      # Agent/Skill 配置
│   └── skills/
│       └── mq-middleware/SKILL.md
├── .env                          # 本地环境变量
├── .env.example                  # 环境变量样例
├── AGENTS.md                     # 项目级 Agent 说明
├── README.md                     # 项目说明
├── docker-compose.yml            # 本地依赖编排
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
│   │   ├── markdown_parser/
│   │   │   ├── llm_integration.py
│   │   │   ├── orchestrator.py
│   │   │   └── provider_clients.py
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
│   │   │   └── pdf/
│   │   │       └── backends/
│   │   └── splitter/
│   ├── models/                   # ORM 模型
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
│   └── utils/
│       ├── file_downloader.py
│       ├── logger.py
│       └── text_formatter.py
└── tests/                        # 测试目录
```


## 配置约定

- 所有运行时配置统一从 [src/config.py](/Users/jixu/Project/Agent/toLink-Rag/src/config.py) 的 `Settings` 读取。
- 本地环境变量样例参考 [.env.example](/Users/jixu/Project/Agent/toLink-Rag/.env.example)。
- 不要硬编码敏感信息；新增配置时同步更新 `Settings` 和 `.env.example`。



## 工作方式

- 先读现有结构，再落代码，不基于想象扩目录。
- 优先做与当前仓库约定一致的最小改动。
- 涉及 MQ、配置、启动流程、脚本目录时，以本文件和 `mq-middleware` skill 为准。
