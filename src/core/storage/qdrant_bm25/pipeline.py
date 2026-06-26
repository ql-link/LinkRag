"""Qdrant BM25 入库管线：与 ``EsIndexingPipeline`` 鸭子兼容的 BM25 写入后端。

对外暴露相同的两个方法签名，使 ``run_es_indexing`` / ``DocumentDeletePurger`` 等
编排层无需感知后端差异（靠 ``BM25_BACKEND`` 工厂切换）：

- ``write_es_index(plan, *, db) -> EsIndexingResult``
- ``delete_document_index(*, user_id, dataset_id, doc_id) -> int``

与 ES 入库管线的差异（均已对齐外层语义）：

- **写入侧只用 coarse**：先做 coarse 单路（BM25 named vector ``bm25_coarse``）；
  fine 作为第二步可再加 ``bm25_fine``。chunk 校验仍要求 coarse+fine 均非空，
  与 ES 灌入规则一致（便于两后端对照评测）。
- **文档级全量重建**：与 ES 一致，由外层先 ``delete_document_index`` 再
  ``write_es_index`` 编排；Qdrant upsert 按 chunk_id 幂等覆盖。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.core.preprocessor.models import ChunkWithTokens, FilePostIndexPlan
from src.core.storage.chunks.repository import ChunkRepository
from src.core.storage.es.models import EsIndexingResult
from src.utils.logger import logger

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
    ) -> None:
        self._store = store or QdrantBm25Store()
        self._chunk_repository = chunk_repository or ChunkRepository()
        self._encoder = encoder or build_encoder_from_settings()

    async def write_es_index(self, plan: FilePostIndexPlan, *, db: Any) -> EsIndexingResult:
        """写一个文件的 post-index plan 到 Qdrant BM25 并回写 chunk es_status。"""

        total = len(plan.chunks_with_tokens)
        if total == 0:
            return EsIndexingResult(total_items=0, indexed_items=0)

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
            vector = self._encoder.encode_document(chunk.coarse_tokens.split())
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
                logger.error(
                    "[QdrantBm25] write failed doc_id={} chunks={} error={}",
                    meta.doc_id,
                    len(points),
                    exc,
                )

        # 4. 状态回写（与 ES pipeline 同语义）。
        await self._mark_status(db, success_ids, failed_errors)

        failed_item_ids = [chunk_id for chunk_id, _ in failed_errors]
        failure_reason = None
        if failed_item_ids:
            failure_reason = (
                "QDRANT_BM25_INDEXING_FAILED: BM25入库失败；"
                f"total={total}, indexed={len(success_ids)}, failed={len(failed_item_ids)}"
            )
        return EsIndexingResult(
            total_items=total,
            indexed_items=len(success_ids),
            failed_item_ids=failed_item_ids,
            failure_reason=failure_reason,
            succeeded_item_ids=success_ids,
        )

    async def delete_document_index(
        self, *, user_id: int, dataset_id: int, doc_id: int
    ) -> int:
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
