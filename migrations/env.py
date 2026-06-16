"""Alembic 运行环境

- DB URL 来自 src.config.settings.DATABASE_URL（已是 mysql+pymysql:// 同步 driver）。
- target_metadata 合并了项目中所有 SQLAlchemy Base 的 MetaData，以便 autogenerate
  能 diff 出全部表/列变更。
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# --- 项目导入 ----------------------------------------------------------------
# 模型导入仅 autogenerate 时必需（用于 diff metadata vs DB）。
# `alembic upgrade head` 只需要 versions/*.py 即可工作，不依赖模型，
# 因此采用 best-effort 导入：缺依赖也允许 upgrade 运行（CI 不必装重依赖）。
import os

from sqlalchemy import MetaData

# Alembic Config 对象
config = context.config

# 注入运行时 DB URL（同步 driver）。
# 优先级：环境变量 ALEMBIC_DATABASE_URL > settings.DATABASE_URL（若可加载）。
runtime_url = os.environ.get("ALEMBIC_DATABASE_URL")
if not runtime_url:
    try:
        from src.config import settings  # 可能因缺依赖而失败，仅 autogen 必需
        runtime_url = settings.DATABASE_URL
    except Exception:  # noqa: BLE001
        runtime_url = None

if runtime_url:
    config.set_main_option("sqlalchemy.url", runtime_url)

combined_metadata = MetaData()
try:
    from src.models import db_models  # noqa: F401
    from src.models import chunk_record  # noqa: F401
    from src.models import parse_task  # noqa: F401
    from src.models import dataset_parse_config  # noqa: F401
    from src.models.db_models import Base as CoreBase
    from src.models.parse_task import Base as ParseTaskBase
    from src.models.dataset_parse_config import Base as DatasetParseConfigBase

    for base in (CoreBase, ParseTaskBase, DatasetParseConfigBase):
        for table in base.metadata.tables.values():
            table.to_metadata(combined_metadata)
except Exception:  # noqa: BLE001
    # autogenerate 将得到空 metadata；upgrade/downgrade 不受影响。
    pass

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


target_metadata = combined_metadata


def run_migrations_offline() -> None:
    """离线模式：生成 SQL，不连数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：实际连库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
