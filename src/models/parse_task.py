from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def utc_now() -> datetime:
    """返回 UTC 当前时间，供 SQLAlchemy 默认值使用。"""
    return datetime.now(timezone.utc)


class DocumentParseTask(Base):
    """SQLAlchemy ORM: document_parse_task 文件解析表。"""

    __tablename__ = "document_parse_task"
    __table_args__ = (
        UniqueConstraint("document_original_file_id", name="uk_parse_task_original_file"),
        Index("idx_parse_task_dataset_user", "dataset_id", "user_id", "updated_at"),
        Index("idx_parse_task_latest_task", "latest_parse_task_id"),
    )

    id = Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    document_original_file_id = Column(BIGINT(unsigned=True), nullable=False)
    dataset_id = Column(BIGINT(unsigned=True), nullable=False)
    user_id = Column(BIGINT(unsigned=True), nullable=False)
    latest_parse_task_id = Column(String(36), nullable=True)
    original_filename = Column(String(255), nullable=False)
    parse_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class DocumentParsedLog(Base):
    """SQLAlchemy ORM: document_parsed_log 文件解析日志表。"""

    __tablename__ = "document_parsed_log"
    __table_args__ = (
        UniqueConstraint("task_id", name="uk_parse_task_id"),
        Index(
            "idx_parsed_log_original_status",
            "document_original_file_id",
            "task_status",
            "updated_at",
        ),
        Index(
            "idx_parsed_log_parse_task_status",
            "document_parse_task_id",
            "task_status",
            "updated_at",
        ),
    )

    id = Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    task_id = Column(String(36), nullable=False)
    document_original_file_id = Column(BIGINT(unsigned=True), nullable=False)
    document_parse_task_id = Column(BIGINT(unsigned=True), nullable=True)
    trigger_mode = Column(String(20), nullable=False)
    task_status = Column(String(16), nullable=False, default="created")
    failure_reason = Column(String(512), nullable=True)
    parsed_filename = Column(String(255), nullable=True)
    parsed_bucket_name = Column(String(64), nullable=True)
    parsed_object_key = Column(String(512), nullable=True)
    parsed_file_url = Column(String(1024), nullable=True)
    parsed_at = Column(DateTime, nullable=True)
    parse_started_at = Column(DateTime, nullable=True)
    parse_finished_at = Column(DateTime, nullable=True)
    parse_duration_ms = Column(BIGINT, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
