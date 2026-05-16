# 数据库迁移规范（Alembic）

本项目使用 [Alembic](https://alembic.sqlalchemy.org/) 管理 MySQL schema 演进。**任何对 `src/models/**.py` 或 `scripts/db/init.sql` 的改动，必须伴随一个新的 Alembic 迁移文件**，否则 doc-sync CI 会以 `error` 拦截 PR（规则 id：`db-migration-required`）。

## 为什么

`scripts/db/init.sql` 只在空库冷启动时跑一次。改字段后若不写迁移，存量库不会自动 ALTER，CI 的临时库又看不出差异 —— 直到生产真实流量进来才会以 `Unknown column` 形式炸出。本项目过去发生过 3 处此类漂移（已由运维手工修复，存量库已与 init.sql 对齐）。

## 工作流

### 改字段 / 加字段

```bash
# 1. 改 ORM 模型 + init.sql
vim src/models/parse_task.py
vim scripts/db/init.sql

# 2. 自动生成迁移（diff 当前 ORM vs 当前库 schema）
alembic revision --autogenerate -m "add retry_count to parsed_log"

# 3. 一定要 review 生成的脚本 —— autogen 偶尔识别不出 rename / 索引差异
vim migrations/versions/<新文件>.py

# 4. 本地跑一遍验证（建议先在 ephemeral MySQL 上跑，避免污染开发库）
ALEMBIC_DATABASE_URL=mysql+pymysql://root:root@127.0.0.1:3306/tolink_rag_db \
  alembic upgrade head

# 5. 跑测试 → 提 PR（PR diff 必须同时包含 model/init.sql 改动 + migration 文件）
```

### 部署 / 生产

```bash
ALEMBIC_DATABASE_URL=mysql+pymysql://USER:PASS@HOST:3306/tolink_rag_db \
  alembic upgrade head
```

幂等：重复执行无副作用。CI 已用 ephemeral MySQL 校验迁移可执行（详见 `.github/workflows/migrations-check.yml`）。

## 关键约定

- **DB URL**：Alembic 用同步 driver `mysql+pymysql://`。运行时优先读 `ALEMBIC_DATABASE_URL` 环境变量，否则回退到 `src.config.settings.DATABASE_URL`。
- **revision 命名**：`NNNN` 递增 4 位编号 + 日期 + slug，例如 `0004_20260603_add_retry_count.py`。`down_revision` 必须线性指向上一个版本，禁止分叉。
- **幂等写法**：rename / drop 等操作建议先通过 `information_schema` 检查目标是否存在，避免在已修正过的库上重复执行报错。参见 `0002` 与 `0003` 的范式。
- **init.sql 的定位**：仅作冷启动文档，记录"当前 head 版本下完整 schema 应该长什么样"；不再是版本化的 DDL 源。新部署仍可 `mysql < init.sql` 起表，然后 `alembic stamp head` 标记版本。
- **既存库接入**：通过 `alembic stamp 0001` 把"当前生产形态"锁为基线，之后 0002/0003 通过幂等检查在已修正/未修正的库上行为一致。

## CI 校验

| Workflow | 校验内容 |
| --- | --- |
| `.github/workflows/migrations-check.yml` | 跑 ephemeral MySQL 8.0，`mysql < init.sql` → `alembic stamp 0001` → `alembic upgrade head` → 再 upgrade 一次验证幂等 |
| `.github/workflows/docs-sync.yml` | 规则 `db-migration-required` 强制 `src/models/**.py` 或 `init.sql` 改动必须伴随 `migrations/versions/*.py` 新增 |

## 常见操作速查

```bash
alembic history              # 查看版本拓扑
alembic current              # 查看当前库版本
alembic upgrade head         # 升级到最新
alembic downgrade -1         # 回退一个版本（仅本地调试，生产慎用）
alembic stamp <revision>     # 仅更新 alembic_version 表，不执行 SQL
alembic revision -m "msg"    # 手写迁移骨架
alembic revision --autogenerate -m "msg"   # autogen 骨架
```
