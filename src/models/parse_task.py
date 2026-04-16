from sqlalchemy import Column, String, DateTime, Integer
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone
import uuid

Base = declarative_base()


class DocumentParseTask(Base):
    """SQLAlchemy ORM: document_parse_task 表定义"""
    __tablename__ = "document_parse_task"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String(36), index=True, nullable=False)
    file_type = Column(String(10), nullable=False)
    status = Column(String(20), default="PENDING")  # PENDING, PROCESSING, SUCCESS, FAILED

    # 使用 LONGTEXT 支持超长文档内容
    markdown_content = Column(LONGTEXT, nullable=True)

    page_count = Column(Integer, default=0)
    error_message = Column(String(512))
    time_cost_ms = Column(Integer, default=0)

    # 修复 Python 3.12+ 的 datetime.utcnow() 弃用警告
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))