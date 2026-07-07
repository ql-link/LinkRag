"""Manticore BM25 入库管线：与 ``EsIndexingPipeline`` 鸭子兼容的 BM25 写入后端。

对外暴露相同的两个方法签名，使 ``run_es_indexing`` / ``DocumentDeletePurger`` 等
编排层无需感知后端差异（靠 ``BM25_BACKEND`` 工厂切换）：

- ``write_es_index(plan, *, db) -> EsIndexingResult``
- ``delete_document_index(*, user_id, dataset_id, doc_id) -> int``

与 Qdrant 入库管线的差异：不需要 sparse 向量编码（``Bm25SparseEncoder``），
``coarse_tokens``/``fine_tokens`` 预分词字符串直接写进 Manticore 的两个全文字段，
TF/长度归一/IDF 全部交给 Manticore 服务端的 ``bm25f()`` 按对应 dataset 表统计。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.core.preprocessor.models import ChunkWithTokens, FilePostIndexPlan
from src.core.storage.chunks.repository import ChunkRepository
from src.core.storage.es.models import EsIndexingResult
from src.utils.logger import logger

from .store import Bm25Point, ManticoreBm25Store


class ManticoreBm25IndexingPipeline:
    """消费预分词 plan，把 BM25 全文字段 + chunk_type 属性写入 Manticore。"""

    def __init__(
        self,
        *,
        store: ManticoreBm25Store | None = None,
        chunk_repository: ChunkRepository | None = None,
    ) -> None:
        self._store = store or ManticoreBm25Store()
        self._chunk_repository = chunk_repository or ChunkRepository()

    async def write_es_index(self, plan: FilePostIndexPlan, *, db: Any) -> EsIndexingResult:
        """写一个文件的 post-index plan 到 Manticore BM25 并回写 chunk es_status。"""

        total = len(plan.chunks_with_tokens)
        if total == 0:
            return EsIndexingResult(total_items=0, indexed_items=0)

        meta = plan.file_meta
        valid_chunks: list[ChunkWithTokens] = []
        failed_errors: list[tuple[str, str]] = []

        # 逐 chunk 校验（与 ES document_factory / Qdrant 管线同规则）。
        for chunk in sorted(plan.chunks_with_tokens, key=lambda c: c.chunk_index):
            reason = self._validate_chunk(chunk)
            if reason is None:
                valid_chunks.append(chunk)
            else:
                failed_errors.append((chunk.chunk_id or "", reason))

        points = [
            Bm25Point(
                chunk_id=chunk.chunk_id,
                doc_id=meta.doc_id,
                user_id=meta.user_id,
                dataset_id=meta.dataset_id,
                chunk_type=chunk.chunk_type,
                coarse_tokens=chunk.coarse_tokens,
                fine_tokens=chunk.fine_tokens,
            )
            for chunk in valid_chunks
        ]

        success_ids: list[str] = []
        if points:
            try:
                await self._store.ensure_table(meta.dataset_id)
                success_ids = await self._store.upsert_chunks(points)
                verified = set(success_ids)
                for p in points:
                    if p.chunk_id not in verified:
                        failed_errors.append(
                            (p.chunk_id, "manticore_bm25_write: not confirmed by read-back verification")
                        )
            except Exception as exc:
                reason = f"manticore_bm25_write: {exc}"
                failed_errors.extend((p.chunk_id, reason) for p in points)
                logger.error(
                    "[ManticoreBm25] write failed doc_id={} chunks={} error={}",
                    meta.doc_id,
                    len(points),
                    exc,
                )

        await self._mark_status(db, success_ids, failed_errors)

        failed_item_ids = [chunk_id for chunk_id, _ in failed_errors]
        failure_reason = None
        if failed_item_ids:
            failure_reason = (
                "MANTICORE_BM25_INDEXING_FAILED: BM25入库失败；"
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
        """删除某文档在 Manticore BM25 中的全部 chunk（文档级全量重建的删除半步）。

        ``user_id`` 参数只为跟 ES/Qdrant 保持签名一致而保留——Manticore 这边表已经
        按 dataset_id 精确路由，不需要 user_id 参与过滤。
        """

        del user_id
        return await self._store.delete_by_document(dataset_id=dataset_id, doc_id=doc_id)

    async def delete_by_dataset(self, *, dataset_id: int) -> None:
        """dataset 整体删除时的表级清理：ES/Qdrant 没有对应方法，仅 Manticore 实现。

        Manticore 按 dataset_id 物理建表，dataset 删除必须整表 DROP 才能回收，逐文档
        删除干净不了空表本身；调用方（``DocumentDeletePurger``）按 ``hasattr`` 探测
        这个方法是否存在，探测不到时（ES/Qdrant 后端）跳过，行为保持不变。
        """

        await self._store.drop_table(dataset_id)

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
