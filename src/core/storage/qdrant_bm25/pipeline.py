"""Qdrant BM25 入库管线：与 ``EsIndexingPipeline`` 鸭子兼容的 BM25 写入后端。

对外暴露相同的两个方法签名，使 ``run_es_indexing`` / ``DocumentDeletePurger`` 等
编排层无需感知后端差异（靠 ``BM25_BACKEND`` 工厂切换）：

- ``write_es_index(plan, *, db, update_status=True) -> Bm25IndexingResult``
- ``delete_document_index(*, user_id, dataset_id, doc_id) -> int``

与 ES 入库管线的差异（均已对齐外层语义）：

- **coarse + fine 双段编码**：coarse 与 fine 两套 token 编进同一个 sparse 向量的
  隔离 hash 维度空间（named vector ``bm25_text``），单次点积即 coarse+fine 双路真
  BM25，对齐 ES ``multi_match(["coarse_tokens^2", "fine_tokens"])`` 的双字段召回。
  chunk 校验要求 coarse+fine 均非空，与 ES 灌入规则一致。
- **文档级全量重建**：与 ES 一致，由外层先 ``delete_document_index`` 再
  ``write_es_index`` 编排；Qdrant upsert 按 chunk_id 幂等覆盖。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.core.preprocessor.models import ChunkWithTokens, FilePostIndexPlan
from src.core.storage.chunks.repository import ChunkRepository
from src.core.storage.bm25_models import Bm25IndexingResult
from src.utils.logger import logger
from src.observability.logging import safe_exception_stack, truncate_log_value

from .encoder import Bm25SparseEncoder, build_encoder_from_settings
from .store import Bm25Point, QdrantBm25Store


class QdrantBm25IndexingPipeline:
    """消费预分词 plan，把 BM25 sparse 向量 + chunk_type payload 写入 Qdrant。"""

    def __init__(
        self,
        *,
        store: QdrantBm25Store | None = None,
        chunk_repository: ChunkRepository | None = None,
        encoder: Bm25SparseEncoder | None = None,
        update_chunk_status: bool = True,
    ) -> None:
        self._store = store or QdrantBm25Store()
        self._chunk_repository = chunk_repository or ChunkRepository()
        self._update_chunk_status = update_chunk_status
        self._encoder = encoder or build_encoder_from_settings()

    async def write_es_index(
        self,
        plan: FilePostIndexPlan,
        *,
        db: Any,
        update_status: bool = True,
    ) -> Bm25IndexingResult:
        """写一个文件的 plan；补偿模式可由外层统一提交 chunk es_status。"""

        total = len(plan.chunks_with_tokens)
        if total == 0:
            return Bm25IndexingResult(total_items=0, indexed_items=0)

        meta = plan.file_meta
        valid_chunks: list[ChunkWithTokens] = []
        failed_errors: list[tuple[str, str]] = []

        # 1. 逐 chunk 校验（与 ES document_factory 同规则）。
        for chunk in sorted(plan.chunks_with_tokens, key=lambda c: c.chunk_index):
            reason = self._validate_chunk(chunk)
            if reason is None:
                valid_chunks.append(chunk)
            else:
                failed_errors.append((chunk.chunk_id or "", reason))

        # 2. 编码 BM25 sparse 向量；分词后为空向量的 chunk 归为 failed。
        points: list[Bm25Point] = []
        for chunk in valid_chunks:
            vector = self._encoder.encode_document(
                chunk.coarse_tokens.split(), chunk.fine_tokens.split()
            )
            if not vector.indices:
                failed_errors.append(
                    (chunk.chunk_id, "validation: empty sparse vector after tokenization")
                )
                continue
            points.append(
                Bm25Point(
                    chunk_id=chunk.chunk_id,
                    doc_id=meta.doc_id,
                    user_id=meta.user_id,
                    dataset_id=meta.dataset_id,
                    chunk_type=chunk.chunk_type,
                    sparse_vector=vector,
                )
            )

        # 3. 写入 Qdrant（ensure collection + upsert）。失败 → 该批全部记 failed。
        success_ids: list[str] = []
        if points:
            try:
                await self._store.ensure_collection()
                await self._store.upsert_chunks(points)
                success_ids = [p.chunk_id for p in points]
            except Exception as exc:
                reason = f"qdrant_bm25_write: {exc}"
                failed_errors.extend((p.chunk_id, reason) for p in points)
                logger.bind(
                    error_type=type(exc).__name__,
                    error_message=truncate_log_value(exc),
                    stack_trace=safe_exception_stack(exc),
                ).error(
                    "[QdrantBm25] write failed doc_id={} chunks={}",
                    meta.doc_id,
                    len(points),
                )

        # 4. 状态回写（与 ES pipeline 同语义）；测试/受控调用可显式跳过。
        if update_status:
            await self._mark_status(db, success_ids, failed_errors)

        failed_item_ids = [chunk_id for chunk_id, _ in failed_errors]
        failure_reason = None
        if failed_item_ids:
            failure_reason = (
                "QDRANT_BM25_INDEXING_FAILED: BM25入库失败；"
                f"total={total}, indexed={len(success_ids)}, failed={len(failed_item_ids)}"
            )
        return Bm25IndexingResult(
            total_items=total,
            indexed_items=len(success_ids),
            failed_item_ids=failed_item_ids,
            failure_reason=failure_reason,
            succeeded_item_ids=success_ids,
        )

    async def delete_document_index(self, *, user_id: int, dataset_id: int, doc_id: int) -> int:
        """删除某文档在 Qdrant BM25 中的全部 chunk（文档级全量重建的删除半步）。"""

        return await self._store.delete_by_document(
            user_id=user_id, dataset_id=dataset_id, doc_id=doc_id
        )

    async def _mark_status(
        self,
        db: Any,
        success_ids: list[str],
        failed_errors: list[tuple[str, str]],
    ) -> None:
        if not self._update_chunk_status:
            return
        if success_ids:
            await self._chunk_repository.mark_es_success(db, success_ids)
        failed_by_reason: dict[str, list[str]] = defaultdict(list)
        for chunk_id, reason in failed_errors:
            failed_by_reason[reason].append(chunk_id)
        for reason, chunk_ids in failed_by_reason.items():
            await self._chunk_repository.mark_es_failed(db, chunk_ids, error_msg=reason)
        await db.commit()

    @staticmethod
    def _validate_chunk(chunk: ChunkWithTokens) -> str | None:
        """复刻 ES document_factory 的 chunk 校验规则。"""

        if not chunk.chunk_id:
            return "validation: chunk_id is required"
        if chunk.chunk_index is None or chunk.chunk_index < 0:
            return "validation: chunk_index must be non-negative"
        if not isinstance(chunk.coarse_tokens, str) or not chunk.coarse_tokens.strip():
            return "validation: coarse_tokens must be non-empty text"
        if not isinstance(chunk.fine_tokens, str) or not chunk.fine_tokens.strip():
            return "validation: fine_tokens must be non-empty text"
        return None
