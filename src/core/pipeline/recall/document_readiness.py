"""基于 MySQL 当前解析任务的文档级召回可见性门禁。"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Protocol, TypeAlias, TypeVar

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.pipeline.parse_task.post_process.constants import PIPELINE_STATUS_SUCCESS
from src.core.storage.chunks.constants import CHUNK_LIFECYCLE_ACTIVE
from src.core.storage.document_visibility import (
    current_document_join_condition,
    dataset_table,
    document_original_file_table,
)
from src.database import get_db_context
from src.models.chunk_record import ChunkRecordDB
from src.models.parse_task import DocumentParsePipeline, DocumentParseTask
from src.observability.logging import safe_exception_stack, truncate_log_value
from src.utils.logger import logger

DEFAULT_READINESS_BATCH_SIZE = 500

SessionContext: TypeAlias = AbstractAsyncContextManager[AsyncSession]
SessionContextFactory: TypeAlias = Callable[[], SessionContext]


class RoutedHit(Protocol):
    """可由 MySQL 就绪门禁校验的最小召回候选协议。"""

    @property
    def chunk_id(self) -> str:
        """返回 Chunk 业务 ID。"""

        ...

    @property
    def doc_id(self) -> int:
        """返回候选声明的原文档 ID。"""

        ...

    @property
    def dataset_id(self) -> int:
        """返回候选声明的数据集 ID。"""

        ...


RoutedHitT = TypeVar("RoutedHitT", bound=RoutedHit)


class MySqlDocumentReadinessGate:
    """批量过滤当前解析任务尚未整体成功的文档候选。

    该对象不持有 session，可安全注入进进程级 ``RecallPipeline`` 单例。每次调用
    都使用一条短生命周期只读 session；查询失败时异常直接向上抛出，实现 fail
    closed。
    """

    def __init__(
        self,
        *,
        session_context_factory: SessionContextFactory = get_db_context,
        batch_size: int = DEFAULT_READINESS_BATCH_SIZE,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be a positive int")
        self._session_context_factory = session_context_factory
        self._batch_size = batch_size

    async def filter_visible_hits(
        self,
        hits: Sequence[RoutedHitT],
        *,
        user_id: int,
    ) -> list[RoutedHitT]:
        """返回 MySQL 已确认可见的候选，并保持融合顺序和对象引用。

        可见条件同时包含：chunk 属于请求用户且仍为 ACTIVE；chunk 的文档、数据集
        与 hit payload 一致；``latest_parse_task_id`` 指向的 pipeline 整体 SUCCESS。
        """
        if not hits:
            logger.info(
                "[DocumentReadinessGate] event=filter_complete candidate_count=0 "
                "unique_candidate_count=0 visible_count=0 filtered_count=0 query_ms=0 "
                "filtered_by_routing_or_missing=0 filtered_by_lifecycle=0 "
                "filtered_by_pipeline=0 "
                "filter_reason_precedence=routing_or_missing,lifecycle,pipeline"
            )
            return []

        chunk_ids = list(dict.fromkeys(hit.chunk_id for hit in hits))
        readiness_by_key: dict[tuple[str, int, int], tuple[str, str | None]] = {}
        query_started = time.monotonic()
        try:
            async with self._session_context_factory() as db:
                for batch in self._iter_batches(chunk_ids):
                    result = await db.execute(self._build_query(batch, user_id=user_id))
                    for (
                        chunk_id,
                        doc_id,
                        set_id,
                        lifecycle_status,
                        pipeline_status,
                    ) in result.all():
                        readiness_by_key[(str(chunk_id), int(doc_id), int(set_id))] = (
                            str(lifecycle_status),
                            str(pipeline_status) if pipeline_status is not None else None,
                        )
        except Exception as exc:
            query_ms = int((time.monotonic() - query_started) * 1000)
            logger.bind(
                event="recall_readiness_query_failed",
                outcome="failed",
                user_id=user_id,
                candidate_count=len(hits),
                unique_candidate_count=len(chunk_ids),
                query_ms=query_ms,
                error_type=type(exc).__name__,
                error_message=truncate_log_value(exc),
                stack_trace=safe_exception_stack(exc),
            ).error(
                "[DocumentReadinessGate] event=query_failed candidate_count={} "
                "unique_candidate_count={} query_ms={} user_id={} error_type={}",
                len(hits),
                len(chunk_ids),
                query_ms,
                user_id,
                type(exc).__name__,
            )
            raise

        visible: list[RoutedHitT] = []
        filtered_by_routing_or_missing = 0
        filtered_by_lifecycle = 0
        filtered_by_pipeline = 0
        for hit in hits:
            readiness = readiness_by_key.get((hit.chunk_id, hit.doc_id, hit.dataset_id))
            if readiness is None:
                filtered_by_routing_or_missing += 1
                continue
            lifecycle_status, pipeline_status = readiness
            # 每个候选只归入一个首要过滤原因，确保分类计数之和等于总过滤数；
            # 此优先级已进入日志契约，不能随意调整。
            if lifecycle_status != CHUNK_LIFECYCLE_ACTIVE:
                filtered_by_lifecycle += 1
            elif pipeline_status != PIPELINE_STATUS_SUCCESS:
                filtered_by_pipeline += 1
            else:
                visible.append(hit)
        query_ms = int((time.monotonic() - query_started) * 1000)
        logger.info(
            "[DocumentReadinessGate] event=filter_complete candidate_count={} "
            "unique_candidate_count={} visible_count={} filtered_count={} query_ms={} "
            "filtered_by_routing_or_missing={} filtered_by_lifecycle={} "
            "filtered_by_pipeline={} "
            "filter_reason_precedence=routing_or_missing,lifecycle,pipeline",
            len(hits),
            len(chunk_ids),
            len(visible),
            len(hits) - len(visible),
            query_ms,
            filtered_by_routing_or_missing,
            filtered_by_lifecycle,
            filtered_by_pipeline,
        )
        return visible

    @staticmethod
    def _build_query(chunk_ids: Sequence[str], *, user_id: int):
        """构建同时校验 Chunk 路由、数据集所有权和当前 pipeline 的批量 SQL。"""

        return (
            select(
                ChunkRecordDB.chunk_id,
                ChunkRecordDB.doc_id,
                ChunkRecordDB.set_id,
                ChunkRecordDB.lifecycle_status,
                DocumentParsePipeline.pipeline_status,
            )
            .outerjoin(
                DocumentParseTask,
                and_(
                    DocumentParseTask.document_original_file_id == ChunkRecordDB.doc_id,
                    DocumentParseTask.user_id == ChunkRecordDB.user_id,
                    DocumentParseTask.dataset_id == ChunkRecordDB.set_id,
                ),
            )
            .outerjoin(
                DocumentParsePipeline,
                current_document_join_condition(),
            )
            .join(dataset_table, dataset_table.c.id == DocumentParseTask.dataset_id)
            .join(
                document_original_file_table,
                document_original_file_table.c.id == DocumentParseTask.document_original_file_id,
            )
            .where(
                ChunkRecordDB.chunk_id.in_(chunk_ids),
                ChunkRecordDB.user_id == user_id,
                dataset_table.c.user_id == user_id,
                dataset_table.c.status.collate("utf8mb4_unicode_ci") == "ACTIVE",
                dataset_table.c.is_deleted.is_(False),
                document_original_file_table.c.user_id == user_id,
                document_original_file_table.c.is_deleted.is_(False),
            )
        )

    def _iter_batches(self, values: Sequence[str]) -> Iterator[Sequence[str]]:
        """按配置批大小切分 Chunk ID，避免生成无界 IN 条件。"""

        for offset in range(0, len(values), self._batch_size):
            yield values[offset : offset + self._batch_size]
