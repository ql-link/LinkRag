# Alembic 数据库迁移使用文档

本项目使用 [Alembic](https://alembic.sqlalchemy.org/) 管理 MySQL schema 演进。本文档面向**日常开发者**，覆盖从 0 到 1 的使用路径、典型场景与常见坑。

> 强制规则：改动 `src/models/**.py` 或 `scripts/db/init.sql` 时，PR 必须包含一个新的 `migrations/versions/*.py` 文件，否则 [doc-sync CI](doc_sync.md) 会以 `error` 拦截（规则 id：`db-migration-required`）。

---

## 一、为什么需要迁移工具

`scripts/db/init.sql` 只在空库冷启动时跑一次。改字段后若不写迁移：

- 存量库不会自动 ALTER
- CI 跑的是 init.sql 起的新库，差异看不出来
- 直到生产真实流量进来 → `Unknown column` / `Table doesn't exist`

本项目过去因此发生过 3 处 schema drift（commit `283c834` 后）。Alembic 把每一次 schema 变更落成版本化、幂等、可重放的脚本，从根本上消除"漏跑 SQL"。

---

## 二、心智模型（5 分钟读懂）

```
┌──────────────────┐         ┌──────────────────────┐
│  ORM 模型变更    │  +      │   migrations/        │
│  src/models/*.py │ ─────▶  │   versions/*.py      │
│  init.sql 同步   │         │   （线性 NNNN 递增） │
└──────────────────┘         └──────────┬───────────┘
                                        │ alembic upgrade head
                                        ▼
                              ┌──────────────────────┐
                              │   MySQL              │
                              │  alembic_version=NNN │
                              └──────────────────────┘
```

核心概念：

| 概念 | 含义 |
| --- | --- |
| **revision** | 一次 schema 变更的版本号，4 位递增编号（`0001`/`0002`...） |
| **down_revision** | 当前 revision 的父版本；构成线性链表，禁止分叉 |
| **head** | 链表末端，"最新版本" |
| **alembic_version 表** | Alembic 自动在目标库里维护的一张单字段表，记录当前已升级到的 revision |
| **upgrade()** | 把库从 down_revision 推进到本 revision 的 SQL |
| **downgrade()** | 反向回滚（仅本地调试用，生产基本不跑） |

每次 `alembic upgrade head`：读 `alembic_version` → 找到所有未应用的 revision → 按顺序逐个执行 → 每条成功后更新 `alembic_version`。**幂等**：跑 N 次和跑 1 次一样。

---

## 三、首次接入（一次性）

### 3.1 安装

```bash
pip install -e ".[dev]"   # 已在 pyproject.toml dependencies 里声明
alembic --version          # 验证可执行
```

### 3.2 锁定基线（存量库）

如果你的库是从 `scripts/db/init.sql` 起的（或者已经在生产用了一段时间），需要先告诉 Alembic "当前形态视为 0001"：

```bash
export ALEMBIC_DATABASE_URL="mysql+pymysql://USER:PASS@HOST:3306/tolink_rag_db"
alembic stamp 0001
```

`stamp` **不执行任何 SQL**，只往 `alembic_version` 写一行 `0001`。之后再跑 `alembic upgrade head`，Alembic 知道从 0001 之后继续。

### 3.3 全新空库（冷启动）

```bash
# 方式 A：走 init.sql + stamp（推荐，与现有部署流程一致）
mysql -h HOST -P 3306 -u USER -p tolink_rag_db < scripts/db/init.sql
alembic stamp head    # 当前形态已是 head，直接 stamp 到最新

# 方式 B：从空库一路 upgrade（适合长期演进的小项目，本项目暂不用）
alembic upgrade head
```

> 选 A 的原因：init.sql 里有完整的索引、AUTO_INCREMENT、COMMENT、字符集声明，比 autogenerate 出来的更精细。

---

## 四、日常工作流

### 4.1 改字段 / 加字段 / 加索引

```bash
# 1. 改 ORM 模型 + 同步 init.sql（保持冷启动文档准确）
vim src/models/parse_task.py
vim scripts/db/init.sql

# 2. 让 Alembic diff 出差异并生成迁移骨架
#    （需要本机能连上一个已 stamp 到 head 的 MySQL）
alembic revision --autogenerate -m "add retry_count to parsed_log"
#    → 生成 migrations/versions/0002_YYYYMMDD_add_retry_count.py

# 3. 必须 review 生成的脚本：
#    - autogen 不擅长识别 rename（会被识别为 drop + add，丢数据！）
#    - autogen 不识别索引名变化、CHECK 约束、字符集变化
#    - 写好的 comment / server_default 可能丢失
vim migrations/versions/0002_*.py

# 4. 本地跑一遍验证
alembic upgrade head    # 应用新迁移
alembic downgrade -1    # 回滚验证 downgrade 可逆
alembic upgrade head    # 再升上去

# 5. 跑测试 → 提 PR
pytest tests/unit -q
```

> 没有现成 DB 怎么办？起一个临时 docker：
> ```bash
> docker run --rm -d --name mig-test -e MYSQL_ROOT_PASSWORD=root \
>   -e MYSQL_DATABASE=tolink_rag_db -p 3307:3306 mysql:8.0
> export ALEMBIC_DATABASE_URL="mysql+pymysql://root:root@127.0.0.1:3307/tolink_rag_db"
> mysql -h 127.0.0.1 -P 3307 -uroot -proot tolink_rag_db < scripts/db/init.sql
> alembic stamp head    # 把空库锚到 head
> # 现在可以 autogenerate 了
> ```

### 4.2 手写迁移（不依赖 autogen）

适合 rename、数据回填、复杂 DDL：

```bash
alembic revision -m "rename retries to retry_count"
# 编辑 upgrade() / downgrade()
```

最简手写模板：

```python
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.alter_column(
        "document_parsed_log",
        "retries",
        new_column_name="retry_count",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )

def downgrade() -> None:
    op.alter_column(
        "document_parsed_log",
        "retry_count",
        new_column_name="retries",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
```

### 4.3 部署到测试 / 生产

```bash
export ALEMBIC_DATABASE_URL="mysql+pymysql://USER:PASS@HOST:3306/tolink_rag_db"
alembic current      # 看当前库版本
alembic history      # 看完整版本链
alembic upgrade head # 升级
```

幂等，重复执行无副作用。CI 已在 ephemeral MySQL 上验证过这条命令可执行（见 [.github/workflows/migrations-check.yml](../../.github/workflows/migrations-check.yml)）。

---

## 五、常用命令速查

| 命令 | 用途 |
| --- | --- |
| `alembic current` | 当前库的 revision |
| `alembic history` | 完整版本拓扑 |
| `alembic heads` | 列出所有 head（正常应只有 1 个；多个意味着分叉） |
| `alembic upgrade head` | 升级到最新 |
| `alembic upgrade +1` | 只升一个版本 |
| `alembic upgrade <rev>` | 升级到指定 revision |
| `alembic downgrade -1` | 回退一个（生产慎用） |
| `alembic downgrade base` | 全部回滚（基本只在本地玩） |
| `alembic stamp <rev>` | **不执行 SQL**，只标记版本号 |
| `alembic revision -m "msg"` | 手写迁移骨架 |
| `alembic revision --autogenerate -m "msg"` | autogen diff 当前 model vs 库 |
| `alembic show <rev>` | 显示指定 revision 的内容 |

---

## 六、关键约定

### 6.1 revision 命名

```
NNNN_YYYYMMDD_slug.py
└─┬─┘ └──┬───┘ └─┬┘
  │     │       └─ 用 _ 分隔的简短描述（add_retry_count）
  │     └───────── 创建日期（便于按时间检索）
  └─────────────── 4 位递增编号，写在 revision = "NNNN" 字段
```

**禁止分叉**：`down_revision` 必须指向当前 head。两个 PR 并发生成新版本时，后合入的那个必须 rebase 时改 `down_revision` 指向前一个。

### 6.2 DB URL

- Alembic 必须用**同步** driver：`mysql+pymysql://`
- 优先级：`ALEMBIC_DATABASE_URL` 环境变量 > `src.config.settings.DATABASE_URL`
- 生产部署推荐显式传 `ALEMBIC_DATABASE_URL`，不要复用应用 runtime 的 URL（避免误连）

### 6.3 幂等写法（手工修复过的库要兼容）

如果你已知线上有人手工跑过 ALTER，迁移要能识别"已经是目标态"并跳过：

```python
def _column_exists(bind, table, col) -> bool:
    return bool(bind.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name=:t AND column_name=:c"
    ), {"t": table, "c": col}).scalar())

def upgrade():
    bind = op.get_bind()
    if not _column_exists(bind, "document_parsed_log", "retry_count"):
        op.add_column("document_parsed_log", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
```

### 6.4 init.sql 的定位

- **不是**版本化的 DDL 源
- **是**冷启动文档：记录"当 head 是 NNNN 时，完整 schema 长这样"
- 改字段时**同步更新** init.sql，保持其与最新 head 一致
- doc-sync 规则 `mysql-schema` 强制：改 init.sql 也要改 [docs/reference/mysql_schema.md](../reference/mysql_schema.md)

---

## 七、常见坑

### 7.1 autogen 把 rename 识别成 drop + add

**症状**：autogen 出来的脚本里有 `op.drop_column("old_name")` + `op.add_column("new_name")`，跑下去丢数据。

**做法**：手工改成 `op.alter_column(..., new_column_name=...)`。Alembic 没法从 ORM diff 推断意图，rename 必须人工指明。

### 7.2 autogen 报 "Target database is not up to date"

**症状**：跑 autogenerate 时 Alembic 拒绝工作。

**原因**：目标库的 `alembic_version` 不等于 `head`（要么落后，要么未 stamp）。

**做法**：先 `alembic upgrade head`，或先 `alembic stamp head`（仅当确认库已是 head 形态）。

### 7.3 多人并发改 schema，head 分叉

**症状**：`alembic heads` 输出两行；`alembic upgrade head` 报错 "Multiple head revisions"。

**做法**：rebase 时把后合入的那个 PR 的 `down_revision` 改成前一个 PR 的 revision。或显式合并：`alembic merge -m "merge heads" <rev1> <rev2>`（一般不推荐，破坏线性）。

### 7.4 改了 ORM 但忘改 init.sql

**症状**：doc-sync CI 报 `mysql-schema` warning，新部署的库 schema 与 ORM 不一致。

**做法**：每次写迁移时同步改 init.sql。可以把迁移的 `upgrade()` 中的 DDL 翻译过去。

### 7.5 server_default 写法

ORM 里 `default=0` 不会进 DDL，必须 `server_default="0"` 才会变成 `DEFAULT 0` 落到表上。Alembic autogen 看的是 `server_default`，所以加字段时建议显式写：

```python
sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0")
```

---

## 八、CI 校验

| Workflow | 触发 | 内容 |
| --- | --- | --- |
| [migrations-check.yml](../../.github/workflows/migrations-check.yml) | PR / push to dev,main | ephemeral MySQL 8.0 → `init.sql` → `stamp 0001` → `upgrade head` → 再 upgrade 一次（验证幂等） |
| [docs-sync.yml](../../.github/workflows/docs-sync.yml) | PR / push to dev,main | 规则 `db-migration-required`：`src/models/**.py` 或 `init.sql` 改动必须配 `migrations/versions/*.py` |

---

## 九、参考

- 上游文档：<https://alembic.sqlalchemy.org/en/latest/>
- 现有迁移：[migrations/versions/](../../migrations/versions/)
- 环境配置：[migrations/env.py](../../migrations/env.py)
- doc-sync 规则总览：[doc_sync.md](doc_sync.md)
- 数据库 schema 文档：[docs/reference/mysql_schema.md](../reference/mysql_schema.md)
