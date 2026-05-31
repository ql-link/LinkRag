# Alembic 迁移

本目录由 [Alembic](https://alembic.sqlalchemy.org/) 管理 toLink-Rag 数据库 schema 演进。

详细说明见 [docs/contributing.md §四](../docs/contributing.md#四数据库迁移alembic)。

## 常用命令

```bash
# 升级到最新版本（幂等）
alembic upgrade head

# 查看当前数据库版本
alembic current

# 查看历史
alembic history

# 生成新的迁移（diff ORM model vs 当前库 schema）
alembic revision --autogenerate -m "add foo to bar"

# 手写迁移（不依赖 autogen）
alembic revision -m "rename xxx to yyy"

# 把一个已经手工同步过的库标记为某版本（不执行 SQL）
alembic stamp <revision>
```

## 版本顺序

- `0001_initial`：基线，对应当前 [scripts/db/init.sql](../scripts/db/init.sql) 的全表结构；`upgrade()` 为 no-op，仅作为版本锚点。

> 此前的 3 处历史 schema drift（`document_parse_task` 改名、外键列改名、新增 `document_post_process_pipeline` 表）已由运维手工在存量库修复，不再需要专门的迁移脚本。后续所有 schema 变更从 `0001` 之后线性追加。
