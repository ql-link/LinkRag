"""Parse task 子包内部共享工具。"""

from datetime import datetime, timezone
from typing import Any

from src.models.parse_task import DocumentParsedLog


def now() -> datetime:
    """返回 UTC 当前时间，统一数据库时间语义。"""
    return datetime.now(timezone.utc)


def _to_utc_aware(value: datetime) -> datetime:
    """将 datetime 归一化为 tz-aware UTC。

    naive datetime 视为 UTC 并补上时区，aware datetime 统一换算到 UTC。
    用于消除 ``now()``（tz-aware UTC）与 MySQL ``DATETIME`` 经 SQLAlchemy 读出的
    naive datetime 混用时的 ``can't subtract offset-naive and offset-aware
    datetimes`` 错误。

    前提：项目内 parse_task 相关时间字段均由应用层 UTC 写入（``now()`` /
    ``utc_now``），MySQL ``DATETIME`` 按字面墙钟存取，故 naive 值语义即 UTC。
    切勿将 DB 端 ``func.now()``（服务器本地时区）写入的字段交给本函数处理。
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def duration_ms(started_at: datetime | None, finished_at: datetime) -> int | None:
    """计算解析耗时毫秒数。

    对两端 datetime 做 UTC 归一化以兼容 naive/aware 混用（如 DB 读回的 naive
    ``started_at`` 与 ``now()`` 返回的 aware ``finished_at``）。
    """
    if started_at is None:
        return None
    delta = _to_utc_aware(finished_at) - _to_utc_aware(started_at)
    return int(delta.total_seconds() * 1000)


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
