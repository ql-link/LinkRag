"""Compensation workflows for vector storage consistency."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.core.chunk_fact_storage import ChunkRepository
from src.core.chunk_fact_storage.constants import (
    CHUNK_STATUS_DELETING,
    CHUNK_STATUS_FAILED,
    CHUNK_STATUS_INDEXING,
)
from src.core.qdrant_vector_storage import IndexedPoint, QdrantIndexStore
from src.core.qdrant_vector_storage.point_factory import (
    chunk_from_record,
    indexed_point_from_record,
)
from src.core.splitter.embedding_pipeline import ChunkEmbeddingPipeline
from src.core.splitter.models import EmbeddedChunk
from src.models.chunk_record import ChunkRecordDB
from src.utils.logger import logger

from ._transaction import TransactionalPipelineMixin
from .constants import DEFAULT_INDEXING_STALE_SECONDS
from .models import ChunkIndexingResult, ChunkMutationResult
from .repair_policy import RepairDecision, RepairPolicy


class VectorStorageCompensationPipeline(TransactionalPipelineMixin):
    """Repair failed or stuck chunk index records so MySQL and Qdrant converge."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        repository: ChunkRepository,
        qdrant_store: QdrantIndexStore,
        embedding_pipeline: ChunkEmbeddingPipeline | None = None,
        repair_policy: RepairPolicy | None = None,
        indexing_stale_seconds: int | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.repository = repository
        self.qdrant_store = qdrant_store
        self.embedding_pipeline = embedding_pipeline
        self.repair_policy = repair_policy or RepairPolicy()
        self.indexing_stale_seconds = indexing_stale_seconds or getattr(
            settings,
            "CHUNK_INDEX_INDEXING_STALE_SECONDS",
            DEFAULT_INDEXING_STALE_SECONDS,
        )

    async def retry_delete_failed(
        self,
        *,
        limit: int = 100,
    ) -> ChunkMutationResult:
        """Retry ``DELETING``/``DELETE_FAILED`` rows until Qdrant and MySQL agree."""
        limit = self.repair_policy.normalize_limit(limit)
        if limit <= 0:
            return ChunkMutationResult(total_chunks=0, affected_chunks=0)

        records = await self._load_delete_retry_candidates(limit)
        if not records:
            return ChunkMutationResult(total_chunks=0, affected_chunks=0)

        affected_chunks = 0
        failed_chunk_ids: list[str] = []
        skipped_chunk_ids: list[str] = []

        for record in records:
            claimed = await self._claim_delete_for_retry(record.chunk_id)
            if not claimed:
                skipped_chunk_ids.append(record.chunk_id)
                continue

            try:
                exists = await self.qdrant_store.point_exists(
                    bucket_id=record.bucket_id,
                    chunk_id=record.chunk_id,
                )
                if exists:
                    await self.qdrant_store.delete_points(
                        bucket_id=record.bucket_id,
                        chunk_ids=[record.chunk_id],
                    )
                deleted = await self._mark_deleted([record.chunk_id])
                if deleted:
                    affected_chunks += 1
                else:
                    skipped_chunk_ids.append(record.chunk_id)
                    logger.warning(
                        "[VectorStorageCompensationPipeline] Skipped stale delete completion "
                        f"for {record.chunk_id}."
                    )
            except Exception as exc:
                failed_chunk_ids.append(record.chunk_id)
                await self._mark_delete_failed([record.chunk_id], error_msg=str(exc))
                logger.exception(
                    f"[VectorStorageCompensationPipeline] Failed delete retry for {record.chunk_id}: {exc}"
                )

        return ChunkMutationResult(
            total_chunks=len(records),
            affected_chunks=affected_chunks,
            failed_chunk_ids=failed_chunk_ids,
            skipped_chunk_ids=skipped_chunk_ids,
        )

    async def repair_stale_indexing(self, *, limit: int = 100) -> ChunkMutationResult:
        """Repair stale ``INDEXING`` rows by checking whether their Qdrant point exists."""
        limit = self.repair_policy.normalize_limit(limit)
        if limit <= 0:
            return ChunkMutationResult(total_chunks=0, affected_chunks=0)

        records = await self._load_stale_indexing_candidates(limit)
        if not records:
            return ChunkMutationResult(total_chunks=0, affected_chunks=0)

        affected_chunks = 0
        failed_chunk_ids: list[str] = []
        skipped_chunk_ids: list[str] = []

        for record in records:
            claimed = await self._claim_stale_indexing_for_repair(record.chunk_id)
            if not claimed:
                skipped_chunk_ids.append(record.chunk_id)
                continue

            try:
                exists = await self.qdrant_store.point_exists(
                    bucket_id=record.bucket_id,
                    chunk_id=record.chunk_id,
                )
                decision = self.repair_policy.decide_for_status(
                    record.status,
                    point_exists=exists,
                )
                if decision == RepairDecision.LIGHTWEIGHT_STATUS_REPAIR:
                    repaired = await self._mark_indexed(
                        [record.chunk_id],
                        embedding_model=record.embedding_model,
                    )
                    if repaired:
                        affected_chunks += 1
                    else:
                        skipped_chunk_ids.append(record.chunk_id)
                    continue

                if decision == RepairDecision.MANUAL_REINDEX_REQUIRED:
                    # Missing point means the vector side did not finish; close the row as FAILED
                    # so explicit reindex scheduling can pick it up later.
                    failed = await self._mark_failed(
                        [record.chunk_id],
                        error_msg="Qdrant point missing during stale INDEXING repair.",
                    )
                    if failed:
                        affected_chunks += 1
                        failed_chunk_ids.append(record.chunk_id)
                    else:
                        skipped_chunk_ids.append(record.chunk_id)
                    continue

                skipped_chunk_ids.append(record.chunk_id)
            except Exception as exc:
                failed_chunk_ids.append(record.chunk_id)
                logger.exception(
                    "[VectorStorageCompensationPipeline] Failed stale INDEXING repair "
                    f"for {record.chunk_id}: {exc}"
                )

        return ChunkMutationResult(
            total_chunks=len(records),
            affected_chunks=affected_chunks,
            failed_chunk_ids=failed_chunk_ids,
            skipped_chunk_ids=skipped_chunk_ids,
        )

    async def mark_indexed_if_point_exists(
        self,
        chunk_ids: Sequence[str],
    ) -> ChunkMutationResult:
        """Read-time lightweight repair for ``INDEXING`` rows whose Qdrant point exists."""
        records, skipped_chunk_ids = await self._load_indexing_records(chunk_ids)
        affected_chunks = 0
        failed_chunk_ids: list[str] = []

        for record in records:
            try:
                exists = await self.qdrant_store.point_exists(
                    bucket_id=record.bucket_id,
                    chunk_id=record.chunk_id,
                )
                if not exists:
                    skipped_chunk_ids.append(record.chunk_id)
                    continue

                repaired = await self._mark_indexed(
                    [record.chunk_id],
                    embedding_model=record.embedding_model,
                )
                if repaired:
                    affected_chunks += 1
                else:
                    skipped_chunk_ids.append(record.chunk_id)
            except Exception as exc:
                failed_chunk_ids.append(record.chunk_id)
                logger.exception(
                    "[VectorStorageCompensationPipeline] Failed point-exists status repair "
                    f"for {record.chunk_id}: {exc}"
                )

        return ChunkMutationResult(
            total_chunks=len(chunk_ids),
            affected_chunks=affected_chunks,
            failed_chunk_ids=failed_chunk_ids,
            skipped_chunk_ids=skipped_chunk_ids,
        )

    async def mark_failed_if_point_missing(
        self,
        chunk_ids: Sequence[str],
    ) -> ChunkMutationResult:
        """Explicitly close ``INDEXING`` rows whose Qdrant point is confirmed missing."""
        records, skipped_chunk_ids = await self._load_indexing_records(chunk_ids)
        affected_chunks = 0
        failed_chunk_ids: list[str] = []

        for record in records:
            try:
                exists = await self.qdrant_store.point_exists(
                    bucket_id=record.bucket_id,
                    chunk_id=record.chunk_id,
                )
                if exists:
                    skipped_chunk_ids.append(record.chunk_id)
                    continue

                failed = await self._mark_failed(
                    [record.chunk_id],
                    error_msg="Qdrant point missing during explicit INDEXING repair.",
                )
                if failed:
                    affected_chunks += 1
                    failed_chunk_ids.append(record.chunk_id)
                else:
                    skipped_chunk_ids.append(record.chunk_id)
            except Exception as exc:
                failed_chunk_ids.append(record.chunk_id)
                logger.exception(
                    "[VectorStorageCompensationPipeline] Failed point-missing status repair "
                    f"for {record.chunk_id}: {exc}"
                )

        return ChunkMutationResult(
            total_chunks=len(chunk_ids),
            affected_chunks=affected_chunks,
            failed_chunk_ids=failed_chunk_ids,
            skipped_chunk_ids=skipped_chunk_ids,
        )

    async def reindex_failed_chunks(self, chunk_ids: Sequence[str]) -> ChunkIndexingResult:
        """Explicitly re-vectorize ``FAILED`` rows; automatic scans do not call this."""
        if not chunk_ids:
            return ChunkIndexingResult(total_chunks=0, indexed_chunks=0)
        if self.embedding_pipeline is None:
            return ChunkIndexingResult(
                total_chunks=len(chunk_ids),
                indexed_chunks=0,
                failed_chunk_ids=list(chunk_ids),
            )

        records = await self._load_records(chunk_ids)
        record_map = {
            record.chunk_id: record
            for record in records
            if record.status == CHUNK_STATUS_FAILED
        }
        indexed_chunks = 0
        failed_chunk_ids: list[str] = [
            chunk_id for chunk_id in chunk_ids if chunk_id not in record_map
        ]
        embedding_model: str | None = None

        for record in record_map.values():
            claimed = await self._claim_failed_for_reindex(record.chunk_id)
            if not claimed:
                failed_chunk_ids.append(record.chunk_id)
                continue

            try:
                point, embedding_model = await self._build_reindex_point(record)
                await self.qdrant_store.ensure_collection(
                    bucket_id=record.bucket_id,
                    vector_size=len(point.vector),
                )
                await self.qdrant_store.upsert_points(bucket_id=record.bucket_id, points=[point])
                repaired = await self._mark_indexed(
                    [record.chunk_id],
                    embedding_model=embedding_model,
                )
                if repaired:
                    indexed_chunks += 1
                else:
                    failed_chunk_ids.append(record.chunk_id)
                    await self._delete_qdrant_point_if_record_is_delete_state(
                        chunk_id=record.chunk_id,
                        fallback_bucket_id=record.bucket_id,
                    )
            except Exception as exc:
                failed_chunk_ids.append(record.chunk_id)
                await self._mark_failed([record.chunk_id], error_msg=str(exc))
                logger.exception(
                    "[VectorStorageCompensationPipeline] Failed explicit reindex "
                    f"for {record.chunk_id}: {exc}"
                )

        return ChunkIndexingResult(
            total_chunks=len(chunk_ids),
            indexed_chunks=indexed_chunks,
            failed_chunk_ids=failed_chunk_ids,
            embedding_model=embedding_model,
        )

    async def _load_delete_retry_candidates(self, limit: int) -> list[ChunkRecordDB]:
        async with self.session_factory() as session:
            return await self.repository.list_delete_retry_candidates(
                session,
                limit=limit,
                stale_after_seconds=self.indexing_stale_seconds,
            )

    async def _load_stale_indexing_candidates(self, limit: int) -> list[ChunkRecordDB]:
        async with self.session_factory() as session:
            return await self.repository.list_stale_indexing_candidates(
                session,
                limit=limit,
                stale_after_seconds=self.indexing_stale_seconds,
            )

    async def _load_records(self, chunk_ids: Sequence[str]) -> list[ChunkRecordDB]:
        async with self.session_factory() as session:
            return await self.repository.get_by_chunk_ids(session, chunk_ids)

    async def _load_indexing_records(
        self,
        chunk_ids: Sequence[str],
    ) -> tuple[list[ChunkRecordDB], list[str]]:
        records = await self._load_records(chunk_ids)
        record_map = {
            record.chunk_id: record
            for record in records
            if record.status == CHUNK_STATUS_INDEXING
        }
        return (
            [record_map[chunk_id] for chunk_id in chunk_ids if chunk_id in record_map],
            [chunk_id for chunk_id in chunk_ids if chunk_id not in record_map],
        )

    async def _claim_delete_for_retry(self, chunk_id: str) -> bool:
        return await self._run_in_transaction_with_result(
            lambda session: self.repository.claim_delete_for_retry(session, chunk_id)
        )

    async def _claim_stale_indexing_for_repair(self, chunk_id: str) -> bool:
        return await self._run_in_transaction_with_result(
            lambda session: self.repository.claim_stale_indexing_for_repair(
                session,
                chunk_id,
                stale_after_seconds=self.indexing_stale_seconds,
            )
        )

    async def _claim_failed_for_reindex(self, chunk_id: str) -> bool:
        return await self._run_in_transaction_with_result(
            lambda session: self.repository.claim_failed_for_reindex(session, chunk_id)
        )

    async def _mark_deleted(self, chunk_ids: Sequence[str]) -> bool:
        affected_rows = await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_deleted(
                session,
                chunk_ids,
                expected_status=CHUNK_STATUS_DELETING,
            )
        )
        return affected_rows == len(chunk_ids)

    async def _mark_indexed(
        self,
        chunk_ids: Sequence[str],
        *,
        embedding_model: str | None,
    ) -> bool:
        affected_rows = await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_indexed(
                session,
                chunk_ids,
                embedding_model=embedding_model,
                expected_status=CHUNK_STATUS_INDEXING,
            )
        )
        return affected_rows == len(chunk_ids)

    async def _mark_failed(self, chunk_ids: Sequence[str], *, error_msg: str) -> bool:
        affected_rows = await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_failed(
                session,
                chunk_ids,
                error_msg=error_msg,
                expected_status=CHUNK_STATUS_INDEXING,
            )
        )
        if affected_rows != len(chunk_ids):
            logger.warning(
                "[VectorStorageCompensationPipeline] Failed status rowcount mismatch: "
                f"{affected_rows} != {len(chunk_ids)} for chunks {chunk_ids}."
            )
        return affected_rows == len(chunk_ids)

    async def _mark_delete_failed(self, chunk_ids: Sequence[str], *, error_msg: str) -> bool:
        affected_rows = await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_delete_failed(
                session,
                chunk_ids,
                error_msg=error_msg,
                expected_status=CHUNK_STATUS_DELETING,
            )
        )
        if affected_rows != len(chunk_ids):
            logger.warning(
                "[VectorStorageCompensationPipeline] Delete failed status rowcount mismatch: "
                f"{affected_rows} != {len(chunk_ids)} for chunks {chunk_ids}."
            )
        return affected_rows == len(chunk_ids)

    async def _build_reindex_point(
        self,
        record: ChunkRecordDB,
    ) -> tuple[IndexedPoint, str | None]:
        if self.embedding_pipeline is None:
            raise RuntimeError("embedding pipeline is required for explicit reindex")

        chunk = chunk_from_record(record)
        embedded_chunks = await self.embedding_pipeline.aembed_chunks([chunk])
        if len(embedded_chunks) != 1:
            raise ValueError(
                f"Expected 1 embedded chunk for {record.chunk_id}, got {len(embedded_chunks)}."
            )

        embedded_chunk: EmbeddedChunk = embedded_chunks[0]
        return indexed_point_from_record(record, embedded_chunk), embedded_chunk.embedding_model
