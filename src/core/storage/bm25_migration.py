"""BM25 后端迁移原语：严格双写与不影响主链路的影子读。"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from typing import Any

from src.core.storage.chunks.repository import ChunkRepository
from src.core.storage.es.models import EsIndexingResult
from src.core.storage.es.retrieval_models import Bm25ChunkHit, Bm25RecallRequest
from src.utils.logger import logger


class DualWriteBm25IndexingPipeline:
    """并行写多个 BM25 后端，只有所有后端确认的 chunk 才标记成功。"""

    def __init__(
        self,
        *,
        pipelines: Mapping[str, Any],
        chunk_repository: ChunkRepository | None = None,
    ) -> None:
        if len(pipelines) < 2:
            raise ValueError("dual-write pipeline requires at least two backends")
        self._pipelines = dict(pipelines)
        self._chunk_repository = chunk_repository or ChunkRepository()

    async def write_es_index(self, plan: Any, *, db: Any) -> EsIndexingResult:
        total = len(plan.chunks_with_tokens)
        if total == 0:
            return EsIndexingResult(total_items=0, indexed_items=0)

        backend_names = list(self._pipelines)
        outcomes = await asyncio.gather(
            *(pipeline.write_es_index(plan, db=db) for pipeline in self._pipelines.values()),
            return_exceptions=True,
        )
        results: dict[str, EsIndexingResult | BaseException] = dict(zip(backend_names, outcomes))
        ordered_ids = list(
            dict.fromkeys(
                str(chunk.chunk_id) for chunk in plan.chunks_with_tokens if chunk.chunk_id
            )
        )

        success_sets: list[set[str]] = []
        details: list[str] = []
        for backend, outcome in results.items():
            if isinstance(outcome, BaseException):
                success_sets.append(set())
                details.append(f"{backend}=exception:{outcome}")
                continue
            success_sets.append(set(outcome.succeeded_item_ids))
            if not outcome.is_success:
                details.append(f"{backend}={outcome.failure_reason or 'incomplete'}")

        success_ids = [
            chunk_id
            for chunk_id in ordered_ids
            if all(chunk_id in successes for successes in success_sets)
        ]
        success_set = set(success_ids)
        failed_ids = [chunk_id for chunk_id in ordered_ids if chunk_id not in success_set]

        if success_ids:
            await self._chunk_repository.mark_es_success(db, success_ids)
        if failed_ids:
            detail = "; ".join(details) or "backend success sets differ"
            await self._chunk_repository.mark_es_failed(
                db,
                failed_ids,
                error_msg=f"bm25_dual_write: {detail}"[:2000],
            )
        await db.commit()

        failure_reason = None
        if failed_ids:
            failure_reason = (
                "BM25_DUAL_WRITE_FAILED: "
                f"backends={','.join(backend_names)}, total={total}, "
                f"indexed={len(success_ids)}, failed={len(failed_ids)}"
            )
        return EsIndexingResult(
            total_items=total,
            indexed_items=len(success_ids),
            failed_item_ids=failed_ids,
            failure_reason=failure_reason,
            succeeded_item_ids=success_ids,
        )

    async def delete_document_index(self, *, user_id: int, dataset_id: int, doc_id: int) -> int:
        outcomes = await asyncio.gather(
            *(
                pipeline.delete_document_index(
                    user_id=user_id, dataset_id=dataset_id, doc_id=doc_id
                )
                for pipeline in self._pipelines.values()
            ),
            return_exceptions=True,
        )
        self._raise_delete_errors("document", outcomes)
        deleted = 0
        for value in outcomes:
            if not isinstance(value, BaseException):
                deleted += int(value)
        return deleted

    async def delete_by_dataset(self, *, user_id: int, dataset_id: int) -> None:
        delete_calls = [
            delete(user_id=user_id, dataset_id=dataset_id)
            for pipeline in self._pipelines.values()
            if (delete := getattr(pipeline, "delete_by_dataset", None)) is not None
        ]
        if not delete_calls:
            return
        outcomes = await asyncio.gather(*delete_calls, return_exceptions=True)
        self._raise_delete_errors("dataset", outcomes)

    @staticmethod
    def _raise_delete_errors(scope: str, outcomes: Sequence[Any]) -> None:
        errors = [str(outcome) for outcome in outcomes if isinstance(outcome, BaseException)]
        if errors:
            raise RuntimeError(f"BM25 dual-write {scope} delete failed: {'; '.join(errors)}")


class ShadowComparingBm25Retriever:
    """主读结果原样返回；按稳定采样在后台比较另一个后端的 top-k。"""

    def __init__(
        self,
        *,
        primary: Any,
        shadow: Any,
        primary_name: str,
        shadow_name: str,
        sample_rate: float,
        timeout_seconds: float,
    ) -> None:
        self._primary = primary
        self._shadow = shadow
        self._primary_name = primary_name
        self._shadow_name = shadow_name
        self._sample_rate = sample_rate
        self._timeout_seconds = timeout_seconds
        # 适配器会据此判断跨 dataset 的原始分是否可比；包影子层后不能丢掉主后端能力标记。
        self.score_scope = getattr(primary, "score_scope", "global")
        self._tasks: set[asyncio.Task[Any]] = set()

    async def recall_topk_chunks(self, request: Bm25RecallRequest) -> list[Bm25ChunkHit]:
        sampled = self._is_sampled(request)
        shadow_task: asyncio.Task[list[Bm25ChunkHit]] | None = None
        shadow_started = 0.0
        if sampled:
            shadow_started = time.perf_counter()
            shadow_task = asyncio.create_task(
                asyncio.wait_for(
                    self._shadow.recall_topk_chunks(request), timeout=self._timeout_seconds
                )
            )

        primary_started = time.perf_counter()
        try:
            primary_hits = await self._primary.recall_topk_chunks(request)
        except BaseException:
            if shadow_task is not None:
                shadow_task.cancel()
                with suppress(BaseException):
                    await shadow_task
            raise
        primary_ms = (time.perf_counter() - primary_started) * 1000

        if shadow_task is not None:
            compare_task = asyncio.create_task(
                self._compare(
                    request=request,
                    primary_hits=primary_hits,
                    primary_ms=primary_ms,
                    shadow_task=shadow_task,
                    shadow_started=shadow_started,
                )
            )
            self._tasks.add(compare_task)
            compare_task.add_done_callback(self._tasks.discard)
        return primary_hits

    def _is_sampled(self, request: Bm25RecallRequest) -> bool:
        if self._sample_rate <= 0:
            return False
        if self._sample_rate >= 1:
            return True
        material = f"{request.user_id}:{request.dataset_id}:{request.doc_id}:" + "\x1f".join(
            str(token) for token in request.tokens
        )
        bucket = int.from_bytes(
            hashlib.blake2b(material.encode("utf-8"), digest_size=8).digest(), "big"
        )
        return bucket / float(2**64) < self._sample_rate

    async def _compare(
        self,
        *,
        request: Bm25RecallRequest,
        primary_hits: Sequence[Bm25ChunkHit],
        primary_ms: float,
        shadow_task: asyncio.Task[list[Bm25ChunkHit]],
        shadow_started: float,
    ) -> None:
        try:
            shadow_hits = await shadow_task
        except Exception as exc:
            logger.warning(
                "[BM25Shadow] shadow failed primary={} shadow={} dataset_id={} error={}",
                self._primary_name,
                self._shadow_name,
                request.dataset_id,
                exc,
            )
            return
        shadow_ms = (time.perf_counter() - shadow_started) * 1000
        primary_ids = {hit.chunk_id for hit in primary_hits}
        shadow_ids = {hit.chunk_id for hit in shadow_hits}
        union = primary_ids | shadow_ids
        overlap = len(primary_ids & shadow_ids) / len(union) if union else 1.0
        top1_equal = bool(primary_hits and shadow_hits) and (
            primary_hits[0].chunk_id == shadow_hits[0].chunk_id
        )
        logger.info(
            "[BM25Shadow] primary={} shadow={} dataset_id={} top_k={} "
            "primary_hits={} shadow_hits={} overlap={:.4f} top1_equal={} "
            "primary_ms={:.2f} shadow_ms={:.2f}",
            self._primary_name,
            self._shadow_name,
            request.dataset_id,
            request.top_k,
            len(primary_hits),
            len(shadow_hits),
            overlap,
            top1_equal,
            primary_ms,
            shadow_ms,
        )

    async def drain(self) -> None:
        """等待当前影子比较完成，供测试或有序停机使用。"""

        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
