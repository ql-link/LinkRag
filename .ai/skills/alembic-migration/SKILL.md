---
name: alembic-migration
description: 编写、校验 Alembic 迁移，保证 schema 演进唯一通过「ORM 模型 + 迁移链」落地，不触碰冻结的 init.sql baseline。 - 当用户改动 src/models/**.py、要求新增/修改表字段、写数据库迁移、对齐 ORM 与 DDL、或排查迁移链断裂时激活。触发示例：'给这个模型加个字段'、'写个迁移'、'alembic 迁移怎么写'、'schema 改了要同步什么'、'升级数据库结构'
when_to_use: "当用户改动 src/models/**.py、要求新增/修改表字段、写数据库迁移、对齐 ORM 与 DDL、或排查迁移链断裂时激活。触发示例：'给这个模型加个字段'、'写个迁移'、'alembic 迁移怎么写'、'schema 改了要同步什么'、'升级数据库结构'。若用户只是要建表 DDL 规范（命名/索引/类型），转 mysql-ddl-conventions；只要同步文档转 doc-maintenance-sync。"
---

# Alembic 迁移（Skill）

## 目的

toLink-Rag 的 schema 权威源是 **ORM 模型 + Alembic 迁移链**。任何字段/表的新增或修改，
都只能改 `src/models/**.py` 并补一条 migration，**不得修改 `scripts/db/init.sql`**
（0001 baseline 冻结快照）。本 skill 把"改模型 → 写迁移 → 校验 → 同步文档"固化为可执行流程。

## 必读文件

1. `src/models/**.py`（本次改动的 ORM 模型，真值源）
2. `migrations/`（迁移链入口）与 `migrations/versions/*.py`（已有迁移，找当前 head）
3. `alembic.ini` / `migrations/env.py`（迁移运行配置与 target_metadata）
4. `scripts/db/init.sql`（**只读**，0001 baseline，禁改）
5. `docs/api/schemas/mysql.md`（数据模型文档，需同步）
6. `.claude/doc-sync-rules.yaml`（机器强制同步规则）

## 硬约束（违反会被 pre-commit / CI 拦截）

- 改 `src/models/**.py` → **必须**新增 `migrations/versions/*.py`。
- 改 `src/models/**.py` → **必须**同步 `docs/api/schemas/mysql.md`。
- **禁止**修改 `scripts/db/init.sql`。
- 新字段一律走 ORM + migration，不要手写裸 DDL 改库。

## 执行流程

1. **确认 head**：找到当前迁移链头（最新 `down_revision` 指向的那个 revision），
   新迁移的 `down_revision` 必须接在 head 后，避免出现多头（multiple heads）。
   ```bash
   .venv/bin/alembic heads
   .venv/bin/alembic history | head
   ```
2. **改 ORM 模型**：在 `src/models/<table>.py` 增改字段/索引，类型与约束遵循
   `mysql-ddl-conventions`（snake_case、状态用 VARCHAR、时间戳、COMMENT 等）。
3. **生成迁移骨架**（autogenerate 后必须人工审查，不可盲信）：
   ```bash
   .venv/bin/alembic revision --autogenerate -m "add xxx to yyy"
   ```
   或手写 `upgrade()/downgrade()`。检查：
   - `upgrade()` 与 ORM 改动**完全一致**（列名、类型、nullable、default、index）；
   - `downgrade()` 能**精确回滚**（drop 对应列/索引），不要留空；
   - 不夹带 autogenerate 误判的无关 diff（如字符集、注释顺序）；
   - 数据迁移（回填、状态重置）显式写在 migration 里，并保证幂等。
4. **本地校验 upgrade/downgrade 往返**：
   ```bash
   .venv/bin/alembic upgrade head
   .venv/bin/alembic downgrade -1
   .venv/bin/alembic upgrade head
   ```
5. **同步文档**：更新 `docs/api/schemas/mysql.md` 中该表的字段说明。
6. **自检**：
   ```bash
   python scripts/check_docs_sync.py --staged
   .venv/bin/alembic heads   # 必须只有一个 head
   ```

## 输出要求

- 给出：改了哪个 ORM 文件、新增的 migration 文件名与 revision/down_revision、
  `mysql.md` 的同步要点。
- 明确 `upgrade()` / `downgrade()` 的对称性说明。
- 若涉及数据回填或状态重置（如清库后重置向量状态），单列「数据迁移」小节并说明幂等性。
- 收尾提示运行 `alembic upgrade head` 与 `check_docs_sync.py`。

## 反面清单（不要这样做）

- ❌ 直接改 `init.sql` 加字段。
- ❌ 只改 ORM 不写 migration（CI 会拦）。
- ❌ `downgrade()` 留 `pass`（无法回滚）。
- ❌ autogenerate 出多个 head 不合并。
- ❌ 用裸 `ALTER TABLE` 手动改线上库绕过迁移链。
