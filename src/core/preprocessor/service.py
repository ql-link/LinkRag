"""Pre-tokenization service that builds file-level ES post-index plans."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.chunk_fact_storage.constants import (
    CHUNK_DELETE_PROTECTED_STATUSES,
    ES_STATUS_FAILED,
    ES_STATUS_PENDING,
    VECTOR_STATUS_SUCCESS,
)
from src.core.chunk_fact_storage.repository import ChunkRepository
from src.database import get_async_session_factory
from src.models.chunk_record import ChunkRecordDB

from .models import ChunkWithTokens, FileIndexMeta, FilePostIndexPlan
from .ragflow_tokenizer import RagFlowTokenizer, TokenizedText


class ChunkTokenizer(Protocol):
    """Tokenizer contract used by the preprocessor service."""

    def tokenize(self, text: str) -> TokenizedText: ...


class PreprocessorError(RuntimeError):
    """Raised when a file cannot be pre-tokenized."""


class Preprocessor:
    """Build ``FilePostIndexPlan`` from stored chunks using RAGFlow tokenization."""

    def __init__(
        self,
        *,
        chunk_repository: ChunkRepository | None = None,
        session_factory: Callable[[], Any] | None = None,
        tokenizer: ChunkTokenizer | None = None,
        tokenizer_factory: Callable[[], ChunkTokenizer] | None = None,
    ) -> None:
        self._chunk_repository = chunk_repository or ChunkRepository()
        self._session_factory = session_factory or get_async_session_factory()
        self._tokenizer = tokenizer
        self._tokenizer_factory = tokenizer_factory or RagFlowTokenizer

    async def build_file_post_index_plan(
        self,
        *,
        doc_id: int,
        task_id: str,
    ) -> FilePostIndexPlan:
        """Build a pre-tokenized plan for chunks that still need ES indexing."""

        async with self._session_factory() as db:
            records = await self._list_chunks_for_pretokenization(db, doc_id)
            if not records:
                return FilePostIndexPlan(
                    file_meta=FileIndexMeta(
                        user_id=0,
                        dataset_id=0,
                        doc_id=doc_id,
                        task_id=task_id,
                    ),
                    chunks_with_tokens=[],
                )

            chunk_ids = [record.chunk_id for record in records]
            try:
                tokenizer = self._get_tokenizer()
                chunks_with_tokens = [
                    self._tokenize_record(tokenizer, record) for record in records
                ]
            except Exception as exc:
                reason = self._format_failure_reason(exc)
                await self._mark_pretokenize_failed(db, chunk_ids, reason)
                raise PreprocessorError(reason) from exc

            first = records[0]
            return FilePostIndexPlan(
                file_meta=FileIndexMeta(
                    user_id=int(first.user_id),
                    dataset_id=int(first.set_id),
                    doc_id=int(first.doc_id),
                    task_id=task_id,
                ),
                chunks_with_tokens=chunks_with_tokens,
            )

    async def _list_chunks_for_pretokenization(
        self,
        db: AsyncSession,
        doc_id: int,
    ) -> list[ChunkRecordDB]:
        stmt = (
            select(ChunkRecordDB)
            .where(ChunkRecordDB.doc_id == doc_id)
            .where(ChunkRecordDB.vector_status == VECTOR_STATUS_SUCCESS)
            .where(ChunkRecordDB.es_status.in_((ES_STATUS_PENDING, ES_STATUS_FAILED)))
            .where(ChunkRecordDB.status.notin_(CHUNK_DELETE_PROTECTED_STATUSES))
            .order_by(ChunkRecordDB.chunk_index.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    def _get_tokenizer(self) -> ChunkTokenizer:
        if self._tokenizer is None:
            self._tokenizer = self._tokenizer_factory()
        return self._tokenizer

    @staticmethod
    def _tokenize_record(
        tokenizer: ChunkTokenizer,
        record: ChunkRecordDB,
    ) -> ChunkWithTokens:
        if record.chunk_index is None or int(record.chunk_index) < 0:
            raise ValueError(f"invalid chunk_index for chunk {record.chunk_id}")

        tokenized = tokenizer.tokenize(record.content)
        coarse_tokens = tokenized.coarse_tokens.strip()
        fine_tokens = tokenized.fine_tokens.strip()
        if not coarse_tokens:
            raise ValueError(f"empty coarse_tokens for chunk {record.chunk_id}")
        if not fine_tokens:
            raise ValueError(f"empty fine_tokens for chunk {record.chunk_id}")

        return ChunkWithTokens(
            chunk_id=record.chunk_id,
            chunk_index=int(record.chunk_index),
            coarse_tokens=coarse_tokens,
            fine_tokens=fine_tokens,
        )

    async def _mark_pretokenize_failed(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        reason: str,
    ) -> None:
        if not chunk_ids:
            return
        await self._chunk_repository.mark_es_failed(
            db,
            list(chunk_ids),
            error_msg=f"pretokenize: {reason}",
        )
        await db.commit()

    @staticmethod
    def _format_failure_reason(exc: Exception) -> str:
        return str(exc) or exc.__class__.__name__
