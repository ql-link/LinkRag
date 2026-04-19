from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone

Base = declarative_base()


class DocumentParseTask(Base):
    """SQLAlchemy ORM: document_parse_task 表定义"""
    __tablename__ = "document_parse_task"

    id = Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    task_id = Column(String(36), unique=True, index=True, nullable=False)
    original_file_id = Column(BIGINT(unsigned=True), index=True, nullable=False)
    file_type = Column(String(32), nullable=False)
    status = Column(String(16), default="pending", nullable=False)
    md_bucket = Column(String(128), nullable=True)
    md_object_key = Column(String(512), nullable=True)
    md_storage_status = Column(String(24), default="pending", nullable=False)
    page_count = Column(Integer, default=0)
    error_message = Column(String(512))
    time_cost_ms = Column(Integer, default=0)

    # 修复 Python 3.12+ 的 datetime.utcnow() 弃用警告
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
