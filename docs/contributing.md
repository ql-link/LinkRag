# Contributing

贡献者指南：分支、提交、代码风格、测试、数据库迁移、文档同步、spec-as-test 工作流。

本篇是开发流程的**唯一规范文档**。其他 docs/ 下的文档只描述项目本身（API、内部架构、运维），不重复这里的内容。

---

## 一、分支与 PR

### 1.1 分支结构

| 分支 | 角色 | 推送方式 |
| --- | --- | --- |
| `main` | 稳定发布分支 | 只能 PR 合入 |
| `dev` | 当前迭代集成分支 | 只能 PR 合入 |
| `feature/<topic>` | 新功能 | 开发者推 |
| `refactor/<topic>` | 重构（不改变行为） | 开发者推 |
| `chore/<topic>` | 依赖、工具、CI | 开发者推 |

**命名约定**：

- 用 `/` 分类型，主题用 kebab-case。
- 主题描述**结果**，不是过程：`feature/pdf-async-image-upload` ✅ / `feature/fix-pdf-bug` ❌。
- 一个分支只做一件事。

### 1.2 提交信息

格式：`<类型>(<可选范围>): <动作> <对象>`

| 类型 | 用途 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | bug 修复 |
| `refactor` | 重构 |
| `docs` | 文档变更 |
| `test` | 测试变更 |
| `chore` | 依赖、工具、CI |
| `perf` | 性能优化 |

要点：

- 主题 ≤ 70 字符，正文按需补"为什么"。
- 中文 / 英文皆可，单仓库内保持一致。
- 一次提交一个原子改动。

### 1.3 PR 流程

```bash
# 1. 起分支
git checkout dev && git pull
git checkout -b feature/<topic>

# 2. 开发、小步提交

# 3. 同步上游
git fetch && git rebase dev

# 4. 自检（见 1.4）
# 5. gh pr create → base = dev
```

合并方式由仓库设置决定，不绕过设置。合并后删除本地与远程分支。

### 1.4 PR 自检清单

- [ ] `black src tests` / `isort src tests` 通过
- [ ] `mypy src` 无新增报错
- [ ] `pytest tests/unit` 全部通过
- [ ] 改动覆盖了对应测试
- [ ] 改 `src/models/**.py` 或 `scripts/db/init.sql` 必须配 Alembic 迁移（见 §五）
- [ ] 触发同步规则的改动已同步对应文档（见 §六）
- [ ] 无未使用依赖

### 1.5 禁忌

- ❌ 直推 `main` / `dev`
- ❌ PR 中夹带不相关改动
- ❌ `--force` 推已被他人 review 的分支
- ❌ `--no-verify` 跳过 pre-commit hook
- ❌ 提交未通过单测的代码

---

## 二、代码风格

### 2.1 工具与配置

配置集中在 [pyproject.toml](../pyproject.toml)：

| 工具 | 用途 | 关键配置 |
| --- | --- | --- |
| `black` | 格式化 | `line-length=100`, `target=py310` |
| `isort` | import 排序 | `profile=black` |
| `mypy` | 静态类型 | 渐进启用 |

提交前顺序：`isort` → `black` → `mypy` → `pytest`。

### 2.2 Python 版本

最低 **3.10**。允许 `match`、`int | str`、`typing.Self`。避免 3.11+ 才有的 `LiteralString`、`tomllib`。

### 2.3 类型注解

| 场景 | 要求 |
| --- | --- |
| 公共函数 / 方法签名 | ✅ 必须 |
| Pydantic 模型字段 | ✅ 必须 |
| 私有 helper / 局部变量 | ⬜ 推荐 |
| 简单 lambda / 短闭包 | ⬜ 可省 |

返回 `None` 也显式写出 `-> None`。

### 2.4 异常

- 不写 `except:` 或 `except Exception:` 然后吞掉——必须重新抛出或转成业务异常。
- 模块异常封装为模块自定义类，参考 [src/core/mq/exceptions.py](../src/core/mq/exceptions.py)。
- 失败时记录足够上下文（task_id、外部资源 key 等）。

### 2.5 异步

- 默认 `async def`；阻塞调用必须 `run_in_executor` 或换异步库。
- 数据库用 `aiomysql`，HTTP 用 `httpx`，Kafka 用 `aiokafka`。

### 2.6 命名

- 模块：snake_case
- 类：PascalCase
- 函数 / 变量：snake_case
- 常量：UPPER_SNAKE_CASE
- 私有：`_internal`

详细规则见 [internals/naming_conventions.md](internals/naming_conventions.md)。

---

## 三、测试

### 3.1 分层

| 层级 | 目录 | 默认运行 | 外部依赖 |
| --- | --- | --- | --- |
| 单元 | `tests/unit/` | ✅ | Mock 隔离 |
| 集成 | `tests/integration/` | ❌ 需 `--run-integration` | 真实 MySQL/MQ/向量库 |
| 连通性 | `tests/integration/test_connectivity.py` | ❌ 需 marker | 仅做 ping |

`tests/integration/` 下所有测试由 `conftest.py` 自动加 `@pytest.mark.integration`。

### 3.2 Markers

配置见 [pyproject.toml](../pyproject.toml) `[tool.pytest.ini_options]`。

| Marker | 何时打 |
| --- | --- |
| `unit` | 默认，可不显式 |
| `integration` | 放 `tests/integration/` 即可（自动加） |
| `connectivity` | 仅 ping 类检查 |
| `real_env` | 触及真实 `.env` 配置；需显式 `-m real_env` 才跑 |

### 3.3 运行命令

```bash
pytest                                      # 仅 unit
pytest tests/unit/api                       # 指定子目录
pytest --run-integration tests/integration  # 含集成
pytest --run-integration -m real_env        # 真实环境
```

### 3.4 单元测试隔离原则

**禁止**：

- ❌ 真实 HTTP（含 LLM、MinerU、内部 API）
- ❌ 真实数据库连接（MySQL、Redis、Qdrant、ES）
- ❌ 真实 MQ producer/consumer
- ❌ 真实文件系统写非临时目录

**应当**：

- ✅ `unittest.mock` / `pytest-mock` 替换外部依赖
- ✅ HTTP 用 `respx` / `httpx.MockTransport`
- ✅ 文件 IO 用 `tmp_path` fixture

### 3.5 异步测试

`pyproject.toml` 配置 `asyncio_mode = "auto"`，`async def test_xxx()` 自动识别，无需装饰器。

### 3.6 新增测试清单

- [ ] 选对层级（unit/integration）
- [ ] 文件名 `test_<module>.py` 或 `test_<behavior>_integration.py`
- [ ] 单元测试无任何真实外部调用
- [ ] 关键 mock 有 `assert_called_with` 校验
- [ ] 覆盖成功路径 + 至少一个失败路径
- [ ] 不依赖测试执行顺序

---

## 四、数据库迁移（Alembic）

### 4.1 强制规则

- 改 `src/models/**.py` → PR 必须包含新的 `migrations/versions/*.py`（同步规则 `db-migration-required`，error 拦截）。
- `scripts/db/init.sql` 是 **0001 baseline 冻结快照**，**禁止改动**（同步规则 `init-sql-frozen`，error 拦截）。

### 4.2 心智模型

```
ORM 变更 (src/models/*.py)  +  migrations/versions/NNNN_*.py
                                     │
                                     │ alembic upgrade head
                                     ▼
                              MySQL.alembic_version 表
```

每次 `alembic upgrade head` 是幂等的：读 `alembic_version` → 应用未运行的 revision → 更新版本号。

### 4.3 日常工作流

```bash
# 1. 改 ORM 模型（不改 init.sql）
vim src/models/parse_task.py

# 2. autogen 生成骨架
alembic revision --autogenerate -m "add retry_count to parsed_log"

# 3. 必须 review 生成的脚本
#    - autogen 把 rename 识别为 drop+add（丢数据！）必须手工改为 alter_column(..., new_column_name=...)
#    - 索引名变化、CHECK 约束、字符集变化、server_default 可能丢失

# 4. 本地验证
alembic upgrade head
alembic downgrade -1
alembic upgrade head

# 5. 跑测试 → 提 PR
pytest tests/unit -q
```

没有现成 DB 时起临时 docker：

```bash
docker run --rm -d --name mig-test -e MYSQL_ROOT_PASSWORD=root \
  -e MYSQL_DATABASE=tolink_rag_db -p 3307:3306 mysql:8.0
mysql -h 127.0.0.1 -P 3307 -uroot -proot tolink_rag_db < scripts/db/init.sql
export ALEMBIC_DATABASE_URL="mysql+pymysql://root:root@127.0.0.1:3307/tolink_rag_db"
alembic stamp 0001
```

### 4.4 命名规则

```
NNNN_YYYYMMDD_slug.py
└─┬─┘ └──┬───┘ └─┬┘
  │     │       └─ 简短描述（add_retry_count）
  │     └───────── 创建日期
  └─────────────── 4 位递增编号，写到 revision="NNNN"
```

**禁止分叉**：`down_revision` 必须指向当前 head。两个 PR 并发时，后合入的 rebase 时改 `down_revision`。

### 4.5 常用命令

| 命令 | 用途 |
| --- | --- |
| `alembic current` | 当前库 revision |
| `alembic history` | 完整版本链 |
| `alembic heads` | 列所有 head（正常 1 个） |
| `alembic upgrade head` | 升到最新 |
| `alembic downgrade -1` | 回退一个 |
| `alembic stamp <rev>` | 仅标记不执行 SQL |
| `alembic revision -m "msg"` | 手写骨架 |
| `alembic revision --autogenerate` | autogen diff |

### 4.6 关键约定

- Alembic 必须用同步 driver：`mysql+pymysql://`。
- DB URL 优先级：`ALEMBIC_DATABASE_URL` 环境变量 > `src.config.settings.DATABASE_URL`。
- `server_default="0"` 才会落到 DDL（`default=0` 只在 ORM 层，不进表）。
- init.sql 不是"最新 schema 文档"；想看最新 schema 跑 `alembic upgrade head` 后 mysqldump。

### 4.7 常见坑

- **autogen 把 rename 识别为 drop+add**：手工改为 `op.alter_column(..., new_column_name=...)`。
- **"Target database is not up to date"**：库的 `alembic_version` ≠ head；先 `alembic upgrade head` 或 `alembic stamp head`。
- **`Duplicate column name`**：同时改了 init.sql 和 migration → 撤掉 init.sql 的改动（这是 `init-sql-frozen` 规则要防的事）。

### 4.8 CI 校验

| Workflow | 触发 | 内容 |
| --- | --- | --- |
| [migrations-check.yml](../.github/workflows/migrations-check.yml) | PR/push dev,main | ephemeral MySQL → init.sql → stamp 0001 → upgrade head → 再 upgrade（验幂等） |
| [docs-sync.yml](../.github/workflows/docs-sync.yml) | PR/push dev,main | 见 §六 |

---

## 五、文档同步规则

### 5.1 触发规则一览

机器执行版本：[.claude/doc-sync-rules.yaml](../.claude/doc-sync-rules.yaml)。本表是人读视图。

| 改动 | 同步位置 | 级别 |
| --- | --- | --- |
| `src/models/**.py` | [docs/api/schemas/mysql.md](api/schemas/mysql.md) | ❌ error |
| `src/models/**.py` | 新增 `migrations/versions/*.py` | ❌ error |
| `scripts/db/init.sql` | **禁止改动** | ❌ error |
| `src/core/mq/messages/**` | [docs/api/mq_contracts.md](api/mq_contracts.md) + [docs/internals/mq.md](internals/mq.md) | ❌ error |
| `src/core/pipeline/parse_task/**` | [docs/internals/parse_task_pipeline.md](internals/parse_task_pipeline.md) | ❌ error |

> 仅保留 error 级规则。内部模块文档同步由 PR 评审兜底，不由 hook 强制。

### 5.2 严格度

- **error**：阻止 commit / merge。`scripts/check_docs_sync.py` 在 pre-commit 和 CI 上拦截。
- **warning**：本项目目前不使用 warning 级规则（避免"假阻拦"）。如果发现失同步是普遍问题，应升级为 error 并加规则，而不是加 warning。

### 5.3 工具与触发时点

```
.claude/doc-sync-rules.yaml      # 规则定义
scripts/check_docs_sync.py       # 检测脚本
.pre-commit-config.yaml          # 本地 hook
.github/workflows/docs-sync.yml  # CI 检查
```

| 时点 | 触发 | 行为 |
| --- | --- | --- |
| `git commit` 前 | pre-commit hook | error 阻止 commit |
| PR / push | GitHub Actions | error 阻止 merge |
| 手动 | `python scripts/check_docs_sync.py --staged` | 输出违规清单 |

### 5.4 手动运行

```bash
python scripts/check_docs_sync.py --staged          # 检查暂存区
python scripts/check_docs_sync.py --working         # 检查工作区
python scripts/check_docs_sync.py --base origin/dev # 检查相对分支
python scripts/check_docs_sync.py --self-check      # 仅验证 yaml 合法
```

### 5.5 新增规则

只在出现新的"代码改动 → 文档失同步会引发集成 bug"关系时新增。流程：

1. 编辑 `.claude/doc-sync-rules.yaml`，加规则（参考已有格式）。
2. `python scripts/check_docs_sync.py --self-check` 验证。
3. 同步本节 §5.1 的人读表。

### 5.6 紧急绕过

需要绕过时（如 P0 hotfix）：本地 `git commit --no-verify`。事后**必须**补 follow-up PR 同步文档。

---

## 六、spec-as-test 工作流（feature 开发）

涉及一个新功能从想法到合入的全流程时使用。短小改动（一行 bugfix、一处配置）直接 PR 即可，不必走全流程。

### 6.1 产物（本地，不入 git）

每个 feature 在 [.specs/](../.specs/) 下建一个目录，依次产出：

| 文件 | 角色 | 由谁/何时产出 |
| --- | --- | --- |
| `brief.md` | 需求理解 + 待确认项 | 接到需求 → 开发者初稿 → 与提需者迭代到冻结 |
| `acceptance.feature` | Gherkin 验收契约（机器可消费） | brief 冻结后 |
| `technical_design.md` | 技术方案 | acceptance 冻结后 |
| `implementation_report.md` | 实施记录、决策、遗留 | 开发完成后 |

`.specs/` **整目录已 git-ignored**——这些文件只活在本地工作目录，不进版本控制。

### 6.2 合并前沉淀

PR 合并前，把 `.specs/<feature>/` 里**有长期价值**的东西搬出去：

| 来自 `.specs/` | 沉淀到 |
| --- | --- |
| 关键设计决策、风险、权衡 | PR 描述 |
| 可执行的 Gherkin 场景 | `tests/acceptance/features/<name>.feature` + `tests/acceptance/test_<name>.py` + step 实现 |
| 新模块或边界变化 | `docs/internals/<module>.md` |
| 新对外契约 | `docs/api/` 对应文件 |
| 新配置项 | `docs/ops/configure.md` |
| 数据库表变化 | `docs/api/schemas/mysql.md` + Alembic 迁移 |

### 6.3 合并后清理

合并后**必须** `rm -rf .specs/<feature>/`。`brief.md` / `technical_design.md` / `implementation_report.md` 是一次性产物，长期留着就是误导信息。

需要查阅历史时：

```bash
git log --all --oneline -- '.specs/<feature>/'
git show <commit-sha>:.specs/<feature>/brief.md
```

### 6.4 关联 skills

`.ai/skills/` 下有对应自动化 skill：`brief-generator` / `acceptance-generator` / `technical-design` / `implementation-execution`。在 Agent 模式下按顺序触发即可。

详见 [.specs/README.md](../.specs/README.md)。

---

## 七、文档体系约定（修改 docs/ 前必读）

### 7.1 目录职责

| 目录 | 描述对象 | 受众 |
| --- | --- | --- |
| `docs/api/` | 对外契约（HTTP/MQ/Schema/错误码） | Java 业务方、对接方 |
| `docs/internals/` | 代码内部实现（模块、约定、流程） | 内部开发者 |
| `docs/ops/` | 部署与配置 | 运维、部署方 |
| `docs/contributing.md` | 本文（开发流程） | 贡献者 |
| `.specs/` | feature 临时交付物 | 开发者 |

### 7.2 单一来源原则

每个事实只在一处正式描述。其他位置只放链接，不复制内容。当文档与代码冲突，**以代码为准修文档**。

### 7.3 不应放进 docs/ 的内容

- 设计草稿、PRD、迭代计划 → `.specs/`
- 会议记录、决策讨论 → PR 描述 / issue
- 临时运维手册 → 运维系统
- 代码实现细节（算法步骤）→ docstring

### 7.4 命名约定

- 文件名 snake_case，全小写。
- 操作类用动词或场景名词（`deploy.md` / `configure.md`）。
- 契约类直接用名词（`http_contracts.md` / `mq_contracts.md`）。

### 7.5 反模式

- ❌ 创建空目录 + 只放一份 README（等于"这里有东西"但实际没有）
- ❌ 同一字段表复制到多个文档（必然漏改）
- ❌ 文档替代代码 docstring（公共接口必须有 docstring）
- ❌ 把 internals 写成教程（教程归 ops 或 brief）

---

## 八、相关入口

- 项目入口：[CLAUDE.md](../CLAUDE.md) / [AGENTS.md](../AGENTS.md)（同一份文件的 symlink）
- 用户介绍：[README.md](../README.md)
- 文档导航：[docs/README.md](README.md)
- spec-as-test 工作流：[.specs/README.md](../.specs/README.md)
