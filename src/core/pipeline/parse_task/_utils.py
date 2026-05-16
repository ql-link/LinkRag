"""Parse task 子包内部共享工具。"""

from datetime import datetime, timezone
from typing import Any

from src.models.parse_task import DocumentParsedLog


def now() -> datetime:
    """返回 UTC 当前时间，统一数据库时间语义。"""
    return datetime.now(timezone.utc)


def duration_ms(started_at: datetime | None, finished_at: datetime) -> int | None:
    """计算解析耗时毫秒数。"""
    if started_at is None:
        return None
    return int((finished_at - started_at).total_seconds() * 1000)


def coerce_optional_int(value: object) -> int | None:
    """将可选 ID 值转换为 int；空值返回 None。"""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return int(value)
    return None


def attach_pipeline_to_log(log_record: DocumentParsedLog, pipeline_record: Any) -> None:
    """在 log_record 上挂载 post-process pipeline 记录，便于同事务内复用。"""
    setattr(log_record, "_post_process_pipeline", pipeline_record)


def get_pipeline_from_log(log_record: DocumentParsedLog) -> Any | None:
    """读取曾在同事务内挂载到 log_record 的 post-process pipeline 记录。"""
    return getattr(log_record, "_post_process_pipeline", None)
