from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Index, UniqueConstraint
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def utc_now() -> datetime:
    """返回 UTC 当前时间，供 SQLAlchemy 默认值使用。"""
    return datetime.now(timezone.utc)


class DatasetParseConfig(Base):
    """SQLAlchemy ORM: dataset_parse_config 数据集级解析/检索参数配置表。

    四个 JSON 列分别承载分块 / Markdown 增强 / PDF / 召回四类配置，各类消费点不同
    （chunking 在 splitter.factory、enhancement 在 markdown_parser.orchestrator、pdf 在
    parse_task_service、recall 在 routes/rag），分列后字段变更的影响范围互相隔离。

    **所有权约定**：表结构（DDL）由本 ORM + Alembic 迁移管理；**行数据的增删改由
    Java 侧负责**（含数据集创建时写默认行、LINK-149 管理接口修改）。Python 侧只读，
    无配置行时由 ``DatasetConfigService`` 返回内存默认，从不写库。
    """

    __tablename__ = "dataset_parse_config"
    __table_args__ = (
        UniqueConstraint("user_id", "dataset_id", name="uk_user_dataset"),
        Index("idx_dataset_parse_config_dataset", "dataset_id"),
    )

    id = Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    user_id = Column(BIGINT(unsigned=True), nullable=False, comment="所属用户 ID")
    dataset_id = Column(
        BIGINT(unsigned=True), nullable=False, comment="所属数据集 ID，对应 dataset.id"
    )
    chunking_config = Column(JSON, nullable=False, comment="分块配置（8 项）")
    enhancement_config = Column(JSON, nullable=False, comment="Markdown 增强配置（4 项）")
    pdf_config = Column(JSON, nullable=False, comment="PDF 解析配置（1 项）")
    recall_config = Column(JSON, nullable=False, comment="召回检索配置（6 项）")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
