# toLink-Rag

`toLink-Rag` 是基于 FastAPI 的 RAG 后端，负责文档解析、分块、向量化索引，并通过 MQ 与 Java 业务系统集成。

本文件是项目的**统一入口**：上半部分给出运行与开发的最小必要信息，下半部分作为各模块文档的导航目录。

> 面向用户的产品介绍与完整快速开始见 [README.md](README.md)。

---

## 一、项目使用

### 1.1 主要代码入口

| 入口 | 路径 |
| --- | --- |
| 应用入口（FastAPI） | [src/main.py](src/main.py) |
| 运行时配置 | [src/config.py](src/config.py) |
| 数据库初始化入口 | [src/database.py](src/database.py) |
| 数据库 DDL（权威来源） | [scripts/db/init.sql](scripts/db/init.sql) |
| HTTP 路由 | [src/api/routes](src/api/routes) |
| 核心业务模块 | [src/core](src/core) |
| 单元测试 | [tests/unit](tests/unit) |
| 集成测试 | [tests/integration](tests/integration) |

### 1.2 快速启动（最小步骤）

```bash
# 1. 启动外部依赖
docker compose up -d

# 2. 安装项目
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. 准备配置（按需修改 .env）
cp .env.example .env

# 4. 初始化数据库
mysql -h 127.0.0.1 -P 3306 -u root -p tolink_rag_db < scripts/db/init.sql

# 5. 启动服务
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

启动后：Swagger UI `http://localhost:8000/docs`，健康检查 `http://localhost:8000/health`。

完整步骤、依赖清单与可选项见 [README.md](README.md#快速开始)。

### 1.3 常用命令

```bash
# 单元测试
.venv/bin/pytest tests/unit -q

# 全部测试
.venv/bin/pytest tests -q

# 启动开发服务
uvicorn src.main:app --reload
```

### 1.4 配置约定

- 所有运行时配置统一通过 [src/config.py](src/config.py) 的 `Settings` 加载。
- 环境变量样例放在 [.env.example](.env.example)，不要硬编码密钥。
- 数据库结构以 [scripts/db/init.sql](scripts/db/init.sql) 为权威，不要在文档中重复 DDL。

---

## 二、文档目录

按需阅读最小必要文档集合，不要把这里当作完整知识库。

### 2.1 架构（`docs/architecture`）

模块级实现、边界、流程说明。修改模块行为或跨模块协作前必读。

| 模块 | 文档 |
| --- | --- |
| 项目结构总览 | [project_structure.md](docs/architecture/project_structure.md) |
| 解析任务流水线 | [parse_task_pipeline_module.md](docs/architecture/parse_task_pipeline_module.md) |
| 文件解析 | [file_parser_module.md](docs/architecture/file_parser_module.md) |
| Markdown 解析与增强 | [markdown_parser_module.md](docs/architecture/markdown_parser_module.md) |
| 分块 | [chunking_module.md](docs/architecture/chunking_module.md) |
| 向量化 | [vectorization_module.md](docs/architecture/vectorization_module.md) |
| MQ 中间件 | [mq_module.md](docs/architecture/mq_module.md) |
| LLM | [llm_module.md](docs/architecture/llm_module.md) |
| 对象存储 | [object_storage_module.md](docs/architecture/object_storage_module.md) |

### 2.2 约定（`docs/conventions`）

跨模块共享的命名、配置、测试规则。修改共享规则前必读。

- [命名约定](docs/conventions/naming_conventions.md)

### 2.3 参考（`docs/reference`）

契约类与生成类资料：API、错误码、数据库与索引模式。修改对外契约时同步更新。

- [API 契约](docs/reference/api_contracts.md)
- [错误码](docs/reference/error_codes.md)
- [MySQL Schema](docs/reference/mysql_schema.md) — 12 张业务表，按业务域分组
- [Qdrant Schema](docs/reference/qdrant_schema.md) — 向量库 collection 与 payload
- [Elasticsearch Schema](docs/reference/elasticsearch_schema.md) — 全文索引文档结构

### 2.4 使用指南（`docs/guides`）

部署、接入、调试、运维等场景化指南。

- [部署指南](docs/guides/deployment.md)
- [配置详解](docs/guides/configuration.md)
- [MQ 集成指南](docs/guides/mq_integration.md)

### 2.5 开发流程（`docs/development`）

分支、提交、测试、PR、文档同步等贡献者规范。

- [文档体系架构](docs/development/documentation_architecture.md) — 设计原则、目录职责、治理机制总览
- [测试规范](docs/development/testing.md)
- [代码风格](docs/development/code_style.md)
- [分支与 PR 流程](docs/development/branching_and_pr.md)
- [文档同步机制](docs/development/doc_sync.md) — 自动检测代码改动是否漏同步文档

---

## 三、按任务查阅路线

| 任务目标 | 先读 |
| --- | --- |
| 理解整体架构与项目结构 | [docs/architecture](docs/architecture) |
| 修改解析主流程、状态流转 | [parse_task_pipeline_module.md](docs/architecture/parse_task_pipeline_module.md) |
| 新增/修改文件解析器 | [file_parser_module.md](docs/architecture/file_parser_module.md) |
| 调整分块策略 | [chunking_module.md](docs/architecture/chunking_module.md) |
| 调整向量化/索引 | [vectorization_module.md](docs/architecture/vectorization_module.md) |
| 修改 MQ 契约或消费链 | [mq_module.md](docs/architecture/mq_module.md) |
| 修改 API、错误码、数据模型 | [docs/reference](docs/reference) |
| 修改命名、配置、测试约定 | [docs/conventions](docs/conventions) |
| 部署、接入、运维 | [docs/guides](docs/guides) |
| 开发流程、协作规范 | [docs/development](docs/development) |

---

## 四、工作规则

- **改动前**：读与任务直接相关的最小文档集合；查阅第五节确认本次会触及哪些必须同步的文档。
- **实现中**：优先复用现有模块边界、配置入口、错误处理；不为业务需求轻易改动 framework 层。
- **改动后**：同步更新受影响的架构、约定或参考文档；不做无关扩写。
- **提交前**：运行 `python scripts/check_docs_sync.py --staged` 自检；启用了 pre-commit hook 时会自动执行。
- **校验时**：按改动范围运行对应测试；文档-only 改动至少检查 diff。
- **MQ 改动**：遵循现有中间件约定与消息契约，必要时更新 [docs/reference](docs/reference)。

---

## 五、文档同步规则

下表是人读的规则总览。**机器执行版本**在 [.claude/doc-sync-rules.yaml](.claude/doc-sync-rules.yaml)，由 pre-commit 与 CI 强制（详见 [doc_sync.md](docs/development/doc_sync.md)）。

| 改动范围 | 同步位置 | 强制级别 |
| --- | --- | --- |
| MySQL DDL 或 ORM | [docs/reference/mysql_schema.md](docs/reference/mysql_schema.md) | ❌ error |
| Qdrant 向量库实现 | [docs/reference/qdrant_schema.md](docs/reference/qdrant_schema.md) | ⚠️ warning |
| Elasticsearch 入库 | [docs/reference/elasticsearch_schema.md](docs/reference/elasticsearch_schema.md) | ⚠️ warning |
| MQ 消息契约（`src/core/mq/messages/`） | [mq_integration.md](docs/guides/mq_integration.md) + [mq_module.md](docs/architecture/mq_module.md) | ❌ error |
| 其他 MQ 模块代码 | [mq_module.md](docs/architecture/mq_module.md) | ⚠️ warning |
| 解析器、Markdown、分块、向量化、LLM 等业务模块 | 对应 `docs/architecture/*_module.md` | ⚠️ warning |
| 解析任务流水线状态机 | [parse_task_pipeline_module.md](docs/architecture/parse_task_pipeline_module.md) | ❌ error |
| API 路由 / Schema | [docs/reference/api_contracts.md](docs/reference/api_contracts.md) | ⚠️ warning |
| 运行时配置 / `.env.example` | [docs/guides/configuration.md](docs/guides/configuration.md) | ⚠️ warning |
| 部署依赖 / `docker-compose.yml` | [docs/guides/deployment.md](docs/guides/deployment.md) | ⚠️ warning |
| 顶层布局 / `pyproject.toml` / `src/main.py` | [docs/architecture/project_structure.md](docs/architecture/project_structure.md) | ⚠️ warning |
| `CLAUDE.md` ↔ `AGENTS.md` | 互相同步（脚本会检查） | ❌ error |

**新增/调整规则**：编辑 `.claude/doc-sync-rules.yaml` 并运行 `python scripts/check_docs_sync.py --self-check` 验证；同步更新本表。
