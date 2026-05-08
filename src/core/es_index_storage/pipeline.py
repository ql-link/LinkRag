"""Minimal file-level Elasticsearch indexing stage."""

from __future__ import annotations

from collections.abc import Sequence

from elasticsearch import AsyncElasticsearch

from src.config import settings
from src.core.mq.messages.parse_task import ParseTaskPayload
from src.core.splitter.models import Chunk
from src.utils.logger import logger

from .models import EsIndexingResult


class EsIndexingPipeline:
    """Index parsed chunks into Elasticsearch and return a file-level summary."""

    def __init__(
        self,
        *,
        client: AsyncElasticsearch | None = None,
        index_name: str | None = None,
    ) -> None:
        self._client = client
        self._index_name = index_name or settings.ES_INDEX_NAME
        self._owns_client = client is None

    async def index_for_parse_task(
        self,
        *,
        payload: ParseTaskPayload,
        chunks: Sequence[Chunk],
    ) -> EsIndexingResult:
        """Index all chunks for the current parse task.

        This stage intentionally returns only a file-level summary. Chunk-level
        ES details stay outside the current implementation scope.
        """
        if not chunks:
            return EsIndexingResult(total_items=0, indexed_items=0)

        try:
            client = self._get_client()
            await self._ensure_index(client)
            failed_item_ids: list[str] = []
            indexed_items = 0
            for index, chunk in enumerate(chunks):
                item_id = self._item_id(payload, index)
                try:
                    await client.index(
                        index=self._index_name,
                        id=item_id,
                        document=self._build_document(payload, chunk, index),
                    )
                    indexed_items += 1
                except Exception as exc:
                    logger.warning(
                        "[EsIndexingPipeline] failed to index chunk: task_id={} item_id={} error={}",
                        payload.task_id,
                        item_id,
                        exc,
                    )
                    failed_item_ids.append(item_id)

            return EsIndexingResult(
                total_items=len(chunks),
                indexed_items=indexed_items,
                failed_item_ids=failed_item_ids,
                failure_reason="ES indexing failed" if failed_item_ids else None,
            )
        except Exception as exc:
            logger.exception(
                "[EsIndexingPipeline] file-level ES indexing failed: task_id={} error={}",
                payload.task_id,
                exc,
            )
            return EsIndexingResult(
                total_items=len(chunks),
                indexed_items=0,
                failed_item_ids=[self._item_id(payload, index) for index, _ in enumerate(chunks)],
                failure_reason=str(exc),
            )
        finally:
            if self._owns_client and self._client is not None:
                await self._client.close()
                self._client = None

    def _get_client(self) -> AsyncElasticsearch:
        if self._client is None:
            self._client = AsyncElasticsearch(
                hosts=[settings.ES_HOST],
                basic_auth=(settings.ES_USER, settings.ES_PASSWORD)
                if settings.ES_USER and settings.ES_PASSWORD
                else None,
            )
        return self._client

    async def _ensure_index(self, client: AsyncElasticsearch) -> None:
        exists = await client.indices.exists(index=self._index_name)
        if not exists:
            await client.indices.create(index=self._index_name)

    @staticmethod
    def _item_id(payload: ParseTaskPayload, index: int) -> str:
        return f"{payload.task_id}-{index}"

    @staticmethod
    def _build_document(
        payload: ParseTaskPayload,
        chunk: Chunk,
        index: int,
    ) -> dict[str, object]:
        return {
            "task_id": payload.task_id,
            "original_file_id": payload.original_file_id,
            "document_parse_task_id": payload.document_parse_task_id,
            "dataset_id": payload.dataset_id,
            "user_id": payload.user_id,
            "source_filename": payload.source_filename,
            "chunk_index": index,
            "content": chunk.content,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "metadata": chunk.metadata or {},
        }
