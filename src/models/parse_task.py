from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def utc_now() -> datetime:
    """返回 UTC 当前时间，供 SQLAlchemy 默认值使用。"""
    return datetime.now(timezone.utc)


class DocumentParseTask(Base):
    """SQLAlchemy ORM: document_parse_file 文件解析表。"""

    __tablename__ = "document_parse_file"
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
    """SQLAlchemy ORM: document_parsed_log 文件解析产物快照表。

    整体任务状态的权威单源是 ``document_parse_pipeline``；本表只承担
    解析产物（Markdown 文件位置、解析起止时间）与触发上下文的快照。
    重试链路通过 ``retry_of_task_id`` 串接上一轮 task_id，便于审计追溯；
    校验失败的重试也会落一行（产物字段为空、retry_of_task_id 仍写入）。
    """

    __tablename__ = "document_parsed_log"
    __table_args__ = (
        UniqueConstraint("task_id", name="uk_parse_task_id"),
        Index(
            "idx_parsed_log_original_file",
            "document_original_file_id",
            "updated_at",
        ),
        Index(
            "idx_parsed_log_parse_file",
            "document_parse_file_id",
            "updated_at",
        ),
        # 重试链反查索引：按上一轮 task_id 追溯重试链路（含失败校验的审计行）。
        Index("idx_parsed_log_retry_of", "retry_of_task_id"),
    )

    id = Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    task_id = Column(String(36), nullable=False)
    document_original_file_id = Column(BIGINT(unsigned=True), nullable=False)
    document_parse_task_id = Column("document_parse_file_id", BIGINT(unsigned=True), nullable=True)
    trigger_mode = Column(String(20), nullable=False)
    parsed_filename = Column(String(255), nullable=True)
    parsed_bucket_name = Column(String(64), nullable=True)
    parsed_object_key = Column(String(512), nullable=True)
    parsed_file_url = Column(String(1024), nullable=True)
    parsed_at = Column(DateTime, nullable=True)
    parse_started_at = Column(DateTime, nullable=True)
    parse_finished_at = Column(DateTime, nullable=True)
    parse_duration_ms = Column(BIGINT, nullable=True)
    # 重试链路上一轮 task_id；首次解析为 NULL，重试由编排层写入 previous_task_id。
    retry_of_task_id = Column(
        String(36),
        nullable=True,
        comment="重试链路上一个 task_id；首次解析为 NULL",
    )
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class DocumentParsePipeline(Base):
    """SQLAlchemy ORM: 文件解析流程状态表（覆盖端到端解析全状态机）。

    ``pipeline_status`` 是整体任务状态的唯一权威；``cleaning_status`` 承载
    先前"解析+上传"语义（现统一称为文档清洗阶段），与 ``chunking_status`` /
    ``vectorizing_status`` / ``pretokenize_status`` / ``es_indexing_status`` /
    ``sparse_vectorizing_status`` 构成 6 个对称的阶段位。

    ``superseded_by_task_id`` 是重试 CAS 第 2 层的目标列：旧 pipeline 行被新
    重试任务"接班"时，由 ``ParsePipelineRepository.mark_superseded`` 写入；
    存在值表示该行已被某次重试占走，不能再被另一次并发重试占走。
    """

    __tablename__ = "document_parse_pipeline"
    __table_args__ = (
        UniqueConstraint("document_parsed_log_id", name="uk_parse_pipeline_parsed_log"),
        Index("idx_parse_pipeline_task_id", "task_id"),
        Index("idx_parse_pipeline_parse_file", "document_parse_file_id", "updated_at"),
        Index("idx_parse_pipeline_status", "pipeline_status", "updated_at"),
        # 重试占用反查索引：审计同一旧 task_id 的接班链路。
        Index("idx_parse_pipeline_superseded", "superseded_by_task_id"),
    )

    id = Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    document_parsed_log_id = Column(BIGINT(unsigned=True), nullable=False)
    task_id = Column(String(36), nullable=False)
    document_original_file_id = Column(BIGINT(unsigned=True), nullable=False)
    document_parse_file_id = Column(BIGINT(unsigned=True), nullable=True)

    pipeline_status = Column(String(20), nullable=False, default="PENDING")
    cleaning_status = Column(
        String(20),
        nullable=False,
        default="PENDING",
        comment="文档清洗（解析+上传）阶段状态: PENDING/PROCESSING/SUCCESS/FAILED",
    )
    chunking_status = Column(String(20), nullable=False, default="PENDING")
    vectorizing_status = Column(String(20), nullable=False, default="PENDING")
    pretokenize_status = Column(
        String(20),
        nullable=False,
        default="PENDING",
        comment="预分词状态: PENDING/PROCESSING/SUCCESS/FAILED",
    )
    es_indexing_status = Column(String(20), nullable=False, default="PENDING")
    sparse_vectorizing_status = Column(
        String(20),
        nullable=False,
        default="PENDING",
        comment="稀疏向量阶段状态: PENDING/PROCESSING/SUCCESS/FAILED",
    )

    failed_stage = Column(String(20), nullable=True)
    recover_from_stage = Column(String(20), nullable=True)
    failure_reason = Column(String(512), nullable=True)

    cleaning_duration_ms = Column(BIGINT, nullable=True, comment="文档清洗阶段耗时，单位毫秒")
    chunking_duration_ms = Column(BIGINT, nullable=True)
    vectorizing_duration_ms = Column(BIGINT, nullable=True)
    pretokenize_duration_ms = Column(
        BIGINT,
        nullable=True,
        comment="预分词耗时，单位毫秒",
    )
    es_indexing_duration_ms = Column(BIGINT, nullable=True)
    sparse_vectorizing_duration_ms = Column(
        BIGINT,
        nullable=True,
        comment="稀疏向量阶段耗时，单位毫秒",
    )
    total_duration_ms = Column(BIGINT, nullable=True)

    # 重试 CAS 第 2 层目标列：被哪个新 task_id 接班，NULL 表示尚未被占用。
    superseded_by_task_id = Column(
        String(36),
        nullable=True,
        comment="被哪个新 task_id 接班（重试 CAS 第 2 层目标列）",
    )

    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
