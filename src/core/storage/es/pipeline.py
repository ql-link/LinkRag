"""File-level Elasticsearch indexing stage."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from elasticsearch import AsyncElasticsearch

from src.config import settings
from src.core.storage.chunks.repository import ChunkRepository
from src.core.preprocessor.models import FilePostIndexPlan

from .batcher import TokenBatch, TokenBatcher
from .client import get_async_es_client
from .document_factory import EsDocumentFactory
from .exceptions import EsBulkError
from .mapping import build_es_index_body
from .models import BulkBatchResult, EsIndexingResult


ClientFactory = Callable[[], AsyncElasticsearch | Awaitable[AsyncElasticsearch]]


class EsIndexingPipeline:
    """Consume pre-tokenized plans and index thin chunk documents into ES."""

    def __init__(
        self,
        *,
        client_factory: ClientFactory | None = None,
        index_name: str | None = None,
        chunk_repository: ChunkRepository | None = None,
    ) -> None:
        self._client_factory = client_factory or (lambda: get_async_es_client(settings))
        self._index_name = index_name or settings.ES_INDEX_NAME
        self._chunk_repository = chunk_repository or ChunkRepository()
        self._document_factory = EsDocumentFactory(
            max_document_bytes=settings.ES_MAX_DOCUMENT_BYTES,
        )
        self._batcher = TokenBatcher(
            document_factory=self._document_factory,
            max_batch_bytes=settings.ES_MAX_TOKEN_BATCH_BYTES,
            max_batch_chunks=settings.ES_MAX_TOKEN_BATCH_CHUNKS,
        )

    async def write_es_index(self, plan: FilePostIndexPlan, *, db: Any) -> EsIndexingResult:
        """Write one file post-index plan to ES and mark chunk ES statuses."""

        total_items = len(plan.chunks_with_tokens)
        if total_items == 0:
            return EsIndexingResult(total_items=0, indexed_items=0)

        client = await self._resolve_client()
        try:
            await self._ensure_index(client)
        except Exception as exc:
            # ensure_index 失败属文件级基础设施故障（ES 不可达/建索引失败），
            # 不是某 chunk 写不进去：不标任何 chunk es_status，按文件级失败返回。
            # failed_item_ids 留空（不暗示 chunk 级失败），is_success 仍为 False
            # （indexed != total）。前缀 ensure_index: 供内部排障区分来源。
            detail = exc.args[0] if isinstance(exc, EsBulkError) and exc.args else str(exc)
            return EsIndexingResult(
                total_items=total_items,
                indexed_items=0,
                failed_item_ids=[],
                failure_reason=f"ensure_index: {detail}",
            )

        batch_result = self._batcher.build_batches(plan)
        succeeded_item_ids: list[str] = []
        failed_errors: list[tuple[str, str]] = []

        if batch_result.failed_errors:
            failed_errors.extend(batch_result.failed_errors)
            await self._mark_validation_failures(db, batch_result.failed_errors)

        for batch in batch_result.batches:
            current_result = await self._bulk_index_batch(client, batch)
            await self._mark_batch_status(db, current_result)
            succeeded_item_ids.extend(current_result.success_ids)
            failed_errors.extend(current_result.failed_errors)

        failed_item_ids = [chunk_id for chunk_id, _ in failed_errors]
        failure_reason = None
        if failed_item_ids:
            failure_reason = (
                "ES_INDEXING_FAILED: ES入库失败；"
                f"total={total_items}, indexed={len(succeeded_item_ids)}, "
                f"failed={len(failed_item_ids)}"
            )

        return EsIndexingResult(
            total_items=total_items,
            indexed_items=len(succeeded_item_ids),
            failed_item_ids=failed_item_ids,
            failure_reason=failure_reason,
            succeeded_item_ids=succeeded_item_ids,
        )

    async def delete_document_index(
        self,
        *,
        user_id: int,
        dataset_id: int,
        doc_id: int,
    ) -> int:
        """删除某文档在 ES 中的全部 chunk 索引（Issue #57 文档级全量重建）。

        删除范围严格限定 user_id + dataset_id + doc_id 三维全等，避免误删其他
        用户 / 数据集 / 文档的索引。返回删除命中的文档数。

        - routing=dataset_id：与写入侧 routing 一致，把删除收敛到目标分片。
        - conflicts="proceed"：容忍并发写导致的版本冲突，不中断删除。
        - refresh=False：不强制刷新；后续全量写入用相同 _id 覆盖即可，无需等待可见性。

        ES 不可达 / 删除请求异常时向上抛，由编排层（_run_es_indexing）判 ES 阶段失败。
        """
        client = await self._resolve_client()
        response = await client.delete_by_query(
            index=self._index_name,
            routing=str(dataset_id),
            query={
                "bool": {
                    "filter": [
                        {"term": {"user_id": user_id}},
                        {"term": {"dataset_id": dataset_id}},
                        {"term": {"doc_id": doc_id}},
                    ]
                }
            },
            conflicts="proceed",
            refresh=False,
        )
        return int(response.get("deleted", 0) or 0)

    async def _resolve_client(self) -> AsyncElasticsearch:
        client = self._client_factory()
        if hasattr(client, "__await__"):
            return await client  # type: ignore[no-any-return]
        return client  # type: ignore[return-value]

    async def _ensure_index(self, client: AsyncElasticsearch) -> None:
        try:
            exists = await client.indices.exists(index=self._index_name)
            if exists:
                return
            try:
                await client.indices.create(
                    index=self._index_name,
                    body=build_es_index_body(
                        shards=settings.ES_INDEX_SHARDS,
                        replicas=settings.ES_INDEX_REPLICAS,
                    ),
                )
            except Exception as exc:
                if "resource_already_exists_exception" in str(exc):
                    return
                raise
        except Exception as exc:
            raise EsBulkError(f"ensure index failed - {exc}") from exc

    async def _bulk_index_batch(
        self,
        client: AsyncElasticsearch,
        batch: TokenBatch,
    ) -> BulkBatchResult:
        operations: list[dict[str, Any]] = []
        for item in batch.items:
            operations.append(item.operation)
            operations.append(item.document)

        try:
            response = await client.bulk(
                index=self._index_name,
                operations=operations,
                refresh=False,
                request_timeout=settings.ES_BULK_REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            reason = f"es_bulk: bulk request failed - {exc}"
            return BulkBatchResult(
                success_ids=[],
                failed_errors=[(chunk_id, reason) for chunk_id in batch.chunk_ids],
            )

        success_ids: list[str] = []
        failed_errors: list[tuple[str, str]] = []
        response_items = response.get("items", [])
        for action, item_response in zip(batch.items, response_items):
            detail = item_response.get("index", {})
            status = int(detail.get("status", 0) or 0)
            if status in (200, 201):
                success_ids.append(action.chunk_id)
                continue
            error = detail.get("error") or {}
            reason = self._extract_error_reason(error)
            failed_errors.append((action.chunk_id, f"es_bulk: {reason}"))

        if len(response_items) < len(batch.items):
            missing_ids = batch.chunk_ids[len(response_items) :]
            failed_errors.extend(
                (chunk_id, "es_bulk: bulk response missing item result")
                for chunk_id in missing_ids
            )

        return BulkBatchResult(success_ids=success_ids, failed_errors=failed_errors)

    async def _mark_batch_status(self, db: Any, batch_result: BulkBatchResult) -> None:
        if batch_result.success_ids:
            await self._chunk_repository.mark_es_success(db, batch_result.success_ids)

        failed_by_reason: dict[str, list[str]] = defaultdict(list)
        for chunk_id, reason in batch_result.failed_errors:
            failed_by_reason[reason].append(chunk_id)
        for reason, chunk_ids in failed_by_reason.items():
            await self._chunk_repository.mark_es_failed(db, chunk_ids, error_msg=reason)

        await db.commit()

    async def _mark_validation_failures(
        self,
        db: Any,
        failed_errors: list[tuple[str, str]],
    ) -> None:
        failed_by_reason: dict[str, list[str]] = defaultdict(list)
        for chunk_id, reason in failed_errors:
            failed_by_reason[reason].append(chunk_id)
        for reason, chunk_ids in failed_by_reason.items():
            await self._chunk_repository.mark_es_failed(db, chunk_ids, error_msg=reason)
        await db.commit()

    @staticmethod
    def _extract_error_reason(error: object) -> str:
        if isinstance(error, dict):
            reason = error.get("reason")
            if reason:
                return str(reason)
            error_type = error.get("type")
            if error_type:
                return str(error_type)
        return str(error or "unknown bulk item failure")
