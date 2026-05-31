# toLink-Rag

`toLink-Rag` 是基于 FastAPI 的 RAG 后端，负责文档解析、分块、向量化索引，并通过 MQ 与 Java 业务系统集成。

本文件是**项目使用入口**，覆盖运行与开发的最小必要信息。文档导航与按角色查阅路线见 [docs/README.md](docs/README.md)。

> 面向用户的产品介绍与完整快速开始见 [README.md](README.md)。

---

## 一、代码入口

| 入口 | 路径 |
| --- | --- |
| 应用入口（FastAPI） | [src/main.py](src/main.py) |
| 运行时配置 | [src/config.py](src/config.py) |
| 数据库初始化入口 | [src/database.py](src/database.py) |
| 数据库 DDL baseline（0001 冻结快照，**不应改动**） | [scripts/db/init.sql](scripts/db/init.sql) |
| 数据库迁移（Alembic，schema 演进的唯一入口） | [migrations/](migrations/) |
| HTTP 路由 | [src/api/routes](src/api/routes) |
| 核心业务模块 | [src/core](src/core) |
| 单元测试 | [tests/unit](tests/unit) |
| 集成测试 | [tests/integration](tests/integration) |

---

## 二、快速启动

```bash
# 1. 启动外部依赖
docker compose up -d

# 2. 安装项目
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. 准备配置
cp .env.example .env

# 4. 初始化数据库
mysql -h 127.0.0.1 -P 3306 -u root -p tolink_rag_db < scripts/db/init.sql

# 5. 启动服务
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

启动后：Swagger UI `http://localhost:8000/docs`，健康检查 `http://localhost:8000/health`。

完整步骤、依赖清单与可选项见 [README.md](README.md#快速开始)。

---

## 三、常用命令

```bash
# 单元测试
.venv/bin/pytest tests/unit -q

# 全部测试
.venv/bin/pytest tests -q

# 启动开发服务
uvicorn src.main:app --reload

# 文档同步自检
python scripts/check_docs_sync.py --staged
```

---

## 四、配置约定

- 所有运行时配置统一通过 [src/config.py](src/config.py) 的 `Settings` 加载。
- 环境变量样例放在 [.env.example](.env.example)，不要硬编码密钥。
- 数据库结构权威源是 **ORM 模型 + Alembic 迁移链**。[scripts/db/init.sql](scripts/db/init.sql) 是 0001 baseline 冻结快照，新增/修改字段一律只改 ORM + 写 migration，**不要**改 init.sql。

---

## 五、文档体系

```
docs/
├── api/          对外契约（HTTP / MQ / Schema / 错误码）
├── internals/    内部实现（模块、约定）
├── ops/          部署与配置
├── contributing.md   贡献者规范（分支、PR、测试、迁移、文档同步）
└── README.md     按读者旅程的一页索引

.specs/           feature 临时交付物（brief / acceptance / design / report）
```

按角色查阅入口：

| 角色 | 看这里 |
| --- | --- |
| 对接方 / 业务方 | [docs/api/](docs/api/) |
| 内部开发者 | [docs/internals/](docs/internals/) |
| 运维 / 部署方 | [docs/ops/](docs/ops/) |
| 贡献者 | [docs/contributing.md](docs/contributing.md) |

详细导航见 [docs/README.md](docs/README.md)。

---

## 六、文档同步规则（机器强制）

只有这些规则会**阻止 commit / merge**。其他文档同步靠 PR 评审。

| 改动 | 必须同步 |
| --- | --- |
| `src/models/**.py` | [docs/api/schemas/mysql.md](docs/api/schemas/mysql.md) |
| `src/models/**.py` | 新增 `migrations/versions/*.py` |
| `scripts/db/init.sql` | **禁止修改**（0001 baseline 冻结） |
| `src/core/mq/messages/**` | [docs/api/mq_contracts.md](docs/api/mq_contracts.md) + [docs/internals/mq.md](docs/internals/mq.md) |
| `src/core/pipeline/parse_task/**` | [docs/internals/parse_task_pipeline.md](docs/internals/parse_task_pipeline.md) |

机器规则在 [.claude/doc-sync-rules.yaml](.claude/doc-sync-rules.yaml)，由 pre-commit 与 CI 强制。详见 [docs/contributing.md §五](docs/contributing.md#五文档同步规则)。

---

## 七、工作规则（Agent / 开发者）

- **改动前**：按角色看 [docs/README.md](docs/README.md) 找到最小必要文档；查第六节确认本次会触发的同步规则。
- **实现中**：优先复用现有模块边界、配置入口、错误处理；不为业务需求轻易改动 framework 层。
- **改动后**：同步更新受影响的对外契约文档；内部模块文档按需更新。
- **提交前**：运行 `python scripts/check_docs_sync.py --staged` 自检；pre-commit hook 会自动执行。
- **校验**：按改动范围运行对应测试。
- **CLAUDE.md / AGENTS.md** 已统一为 `.ai/prompts/project.md` 的 symlink，物理同一份文件。新人 / 新 worktree 初始化运行：`python scripts/setup_ai_links.py`。

---

## 八、回答风格（面向开发者沟通）

- 语言清晰、专业、得体，保持一定分寸；不要过度口语化或大白话。
- 少用生僻术语和生造的比喻（例如"强冻结的线性瀑布"这类说法要避免）；常见技术词可以直接用。
- 确实要用较专业的术语时，顺带用一句话点明它的含义，但不必刻意降到最通俗。
- 先给结论，再讲原因；结构清楚，长短结合，不堆砌名词、也不刻意卖弄简单。
- 目标：读起来顺畅、专业，又不让人被术语挡住。
