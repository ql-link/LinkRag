"""用户可见 Wiki 文档与 Chunk 共用的 SQL 授权谓词。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Boolean, Integer, String, and_, column, table

from src.core.storage.chunks.constants import CHUNK_LIFECYCLE_ACTIVE
from src.models.chunk_record import ChunkRecordDB
from src.models.parse_task import DocumentParsePipeline, DocumentParseTask

# Java 侧管理的两张表没有 Python ORM；轻量 TableClause 只用于显式拼接授权 SQL，
# 避免把非本服务管理的表误纳入 Alembic metadata。
dataset_table = table(
    "dataset",
    column("id", Integer),
    column("user_id", Integer),
    column("status", String),
    column("is_deleted", Boolean),
)
document_original_file_table = table(
    "document_original_file",
    column("id", Integer),
    column("dataset_id", Integer),
    column("user_id", Integer),
    column("is_deleted", Boolean),
)

# 状态值留在存储层本地，避免导入会提前装配运行时的 parse-pipeline 包，
# 从而阻断 Wiki repository 与解析 pipeline 的循环依赖。
_PIPELINE_STATUS_SUCCESS = "SUCCESS"


def current_successful_document_conditions(
    *,
    user_id: int,
    dataset_ids: Sequence[int],
    doc_ids: Sequence[int] | None = None,
) -> tuple[Any, ...]:
    """生成当前文档所有权、数据集状态和解析成功状态的共享 SQL 条件。"""

    conditions: list[Any] = [
        DocumentParseTask.user_id == user_id,
        DocumentParseTask.dataset_id.in_(tuple(dataset_ids)),
        DocumentParsePipeline.task_id.collate("utf8mb4_unicode_ci")
        == DocumentParseTask.latest_parse_task_id.collate("utf8mb4_unicode_ci"),
        DocumentParsePipeline.document_parse_file_id == DocumentParseTask.id,
        DocumentParsePipeline.document_original_file_id
        == DocumentParseTask.document_original_file_id,
        DocumentParsePipeline.pipeline_status.collate("utf8mb4_unicode_ci")
        == _PIPELINE_STATUS_SUCCESS,
        dataset_table.c.id == DocumentParseTask.dataset_id,
        dataset_table.c.user_id == user_id,
        dataset_table.c.status.collate("utf8mb4_unicode_ci") == "ACTIVE",
        dataset_table.c.is_deleted.is_(False),
        document_original_file_table.c.id == DocumentParseTask.document_original_file_id,
        document_original_file_table.c.dataset_id == DocumentParseTask.dataset_id,
        document_original_file_table.c.user_id == user_id,
        document_original_file_table.c.is_deleted.is_(False),
    ]
    if doc_ids is not None:
        conditions.append(DocumentParseTask.document_original_file_id.in_(tuple(doc_ids)))
    return tuple(conditions)


def visible_chunk_conditions(*, user_id: int) -> tuple[Any, ...]:
    """生成 Chunk 所有权、文档路由和 ACTIVE 生命周期的共享 SQL 条件。"""

    return (
        ChunkRecordDB.user_id == user_id,
        ChunkRecordDB.set_id == DocumentParseTask.dataset_id,
        ChunkRecordDB.doc_id == DocumentParseTask.document_original_file_id,
        ChunkRecordDB.lifecycle_status.collate("utf8mb4_unicode_ci") == CHUNK_LIFECYCLE_ACTIVE,
    )


def current_document_join_condition() -> Any:
    """把解析文件行联接到 latest task 指向的当前 pipeline 行。"""

    return and_(
        DocumentParsePipeline.task_id.collate("utf8mb4_unicode_ci")
        == DocumentParseTask.latest_parse_task_id.collate("utf8mb4_unicode_ci"),
        DocumentParsePipeline.document_parse_file_id == DocumentParseTask.id,
        DocumentParsePipeline.document_original_file_id
        == DocumentParseTask.document_original_file_id,
    )
