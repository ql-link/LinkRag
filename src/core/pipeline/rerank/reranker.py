"""召回后重排核心：回填正文 → 消费 Dataset RERANK 快照 → 调用 rerank → 映射输出 / 降级。

职责边界（brief：本期独立交付、不接入召回/生成链路）：
- 上游产出融合候选、下游消费重排结果，均不在本模块——它是一个可独立调用、独立测试的单元。
- 不碰向量化、不碰 LLM 文本生成、不触 ``RecallPipeline`` 纯召回边界。

失败语义：
- **Dataset 未开启 rerank → 降级**：不调用模型，返回当前融合顺序。
- **已开启但精确 RERANK 快照缺失 → 显式失败**：不自行查找其它配置。
- **调用失败 / 返回不可用 → 降级**：返回当前融合顺序候选并标记 ``rerank_applied=False``。

依赖通过构造注入（``content_fetcher`` / ``model_resolver``），便于单测以替身替换 DB 与 LLM。
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from loguru import logger

from src.config import settings
from src.core.pipeline.chunk_content import fetch_chunk_contents
from src.core.pipeline.recall.models import RecallHit
from src.core.pipeline.rerank.models import RerankedHit, RerankRequest, RerankResponse
from src.services.usage_reporter import report_usage_nowait
from src.observability.logging import safe_exception_stack, truncate_log_value

# 注入点签名：正文回填 (chunk_ids, user_id) -> {chunk_id: 正文}
ContentFetcher = Callable[[list[str], int], Awaitable[dict[str, str]]]


def reranked_from_recall(
    hit: RecallHit,
    *,
    rerank_score: float | None = None,
    rerank_rank: int | None = None,
) -> RerankedHit:
    """在 ``RecallHit`` 元信息上补 rerank 字段，保留 fused_score 与各路 scores。

    rerank 未生效（降级）或某候选未拿到分时，``rerank_score`` / ``rerank_rank`` 为 ``None``。
    重排成功映射、软降级、上游硬失败兜底降级共用本函数，保证三处产出的 ``RerankedHit``
    形态严格一致。
    """
    return RerankedHit(
        chunk_id=hit.chunk_id,
        doc_id=hit.doc_id,
        dataset_id=hit.dataset_id,
        fused_score=hit.fused_score,
        scores=hit.scores,
        rerank_score=rerank_score,
        rerank_rank=rerank_rank,
    )


def degrade_to_fusion_order(content_present_hits: list[RecallHit], top_n: int) -> list[RerankedHit]:
    """降级：按当前融合顺序输出候选（rerank 字段置空），截断 ``top_n``。

    入参须为**已过滤掉无正文**的命中——这是降级口径的单一来源：reranker 软降级与
    调用方（runtime）的硬失败兜底都调用本函数，保证不同降级路径产出同一"有正文候选"
    集合、同一长度，不因走哪条降级路而喂给下游不同数量的片段。
    """
    return [reranked_from_recall(h) for h in content_present_hits[:top_n]]


class PostRecallReranker:
    """承接融合后候选，回表取正文并调用 Dataset RERANK 快照重排。"""

    def __init__(
        self,
        *,
        content_fetcher: ContentFetcher = fetch_chunk_contents,
    ) -> None:
        self._fetch = content_fetcher

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        """对融合后候选执行重排，返回重排后候选列表。

        步骤：空候选 → 回填正文 → 缺正文过滤（只记日志）→ 全空短路 →
        按 Dataset 取精确 RERANK 快照 → 调用 rerank（降级点）→ index 映射 → 截断 top_n。
        """
        start = time.perf_counter()
        # 入参校验：top_n 要么不传（取配置默认），要么为正整数。
        # 不校验会让 top_n=0 被静默当默认、负数在末尾 ranked[:top_n] 反向切片丢候选。
        if request.top_n is not None and request.top_n <= 0:
            raise ValueError(f"top_n must be a positive int or None, got {request.top_n!r}")
        top_n = request.top_n if request.top_n is not None else settings.RERANK_DEFAULT_TOP_N

        def _resp(hits: list[RerankedHit], applied: bool) -> RerankResponse:
            elapsed = int((time.perf_counter() - start) * 1000)
            return RerankResponse(request.query, hits, applied, elapsed)

        # 空候选：不查 DB、不调模型。
        if not request.hits:
            return _resp([], False)

        # 正文回填：调用方已批量回填则复用（避免对同批 chunk 重复查库），否则自查。
        # 两条路径都只认本用户 ACTIVE 非空正文；查不到的 chunk 不参与 rerank。
        if request.contents is not None:
            contents = request.contents
        else:
            contents = await self._fetch([h.chunk_id for h in request.hits], request.user_id)
        scored_hits = [h for h in request.hits if contents.get(h.chunk_id)]
        skipped = len(request.hits) - len(scored_hits)
        if skipped:
            # 剔除只记日志，不进返回结构（brief Q5）。
            logger.info(
                "[rerank] skipped {} chunk(s) without content user_id={}",
                skipped,
                request.user_id,
            )

        # 全部缺正文：等同空命中，不调模型。
        if not scored_hits:
            return _resp([], False)

        contexts = request.dataset_contexts or {}
        # 保留融合列表的 slot：每个 Dataset 只在自己的 slot 内换序，
        # 不比较不同 reranker 的原始分数尺度。
        grouped: dict[int, list[RecallHit]] = {}
        for hit in scored_hits:
            grouped.setdefault(hit.dataset_id, []).append(hit)

        ranked_by_dataset: dict[int, list[RerankedHit]] = {}
        applied = False
        for dataset_id, group in grouped.items():
            context = contexts.get(dataset_id)
            if context is None:
                raise ValueError(f"Dataset {dataset_id} execution context is required")
            if not context.config.recall.enable_rerank:
                ranked_by_dataset[dataset_id] = self._degrade(group, len(group))
                continue
            if context.rerank is None:
                raise ValueError(f"Dataset {dataset_id} rerank binding is required")
            ranked, group_applied = await self._rerank_group(
                request=request,
                hits=group,
                contents=contents,
                resolved=context.rerank,
            )
            ranked_by_dataset[dataset_id] = ranked
            applied = applied or group_applied

        offsets = {dataset_id: 0 for dataset_id in ranked_by_dataset}
        slot_filled: list[RerankedHit] = []
        for hit in scored_hits:
            group = ranked_by_dataset[hit.dataset_id]
            offset = offsets[hit.dataset_id]
            slot_filled.append(group[offset])
            offsets[hit.dataset_id] = offset + 1
        return _resp(slot_filled[:top_n], applied)

    async def _rerank_group(self, *, request, hits, contents, resolved):
        documents = [contents[h.chunk_id] for h in hits]
        try:
            result = await resolved.provider.rerank(
                query=request.query,
                documents=documents,
                model=resolved.model_name,
                top_n=None,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.bind(
                event="rerank_model_failed",
                outcome="degraded",
                user_id=request.user_id,
                dataset_id=hits[0].dataset_id,
                config_id=resolved.config_id,
                error_type=type(exc).__name__,
                error_message=truncate_log_value(exc),
                stack_trace=safe_exception_stack(exc),
            ).warning("[rerank] model call failed; keeping dataset fusion slots")
            return self._degrade(hits, len(hits)), False

        usage = getattr(result, "usage", None)
        report_usage_nowait(
            user_id=request.user_id,
            provider_type=resolved.provider_type,
            model_name=resolved.model_name,
            stage="recall",
            operation="rerank",
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=0,
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
            config_id=int(resolved.config_id),
        )
        ranked = self._map_results(hits, result)
        if ranked is None:
            return self._degrade(hits, len(hits)), False
        return ranked, True

    def _map_results(self, scored_hits: list[RecallHit], result) -> list[RerankedHit] | None:
        """把 rerank 返回的 (index, score) 映射回候选，健壮处理越界/重复/缺失。

        - 过滤越界 index、去重重复 index（保留首次出现）。
        - 无任一合法 index → 返回 None（触发降级）。
        - 合法项按 rerank_score 降序编号；未被任何合法 index 命中的有正文候选，
          按当前融合顺序追加为「无分 tail」（rerank_score=None），不丢候选。
        """
        n = len(scored_hits)
        seen: set[int] = set()
        scored: list[tuple[int, float]] = []
        for item in result.results:
            idx = item.index
            if idx < 0 or idx >= n or idx in seen:
                continue
            seen.add(idx)
            scored.append((idx, item.score))

        if not scored:
            return None

        # 已打分候选按 rerank_score 降序排列。
        scored.sort(key=lambda t: t[1], reverse=True)

        ranked: list[RerankedHit] = []
        rank = 1
        for idx, score in scored:
            ranked.append(self._to_hit(scored_hits[idx], score, rank))
            rank += 1
        # 无分 tail：未返回的有正文候选按当前融合顺序追加，rerank_score=None。
        for i, hit in enumerate(scored_hits):
            if i not in seen:
                ranked.append(self._to_hit(hit, None, rank))
                rank += 1
        return ranked

    def _degrade(self, scored_hits: list[RecallHit], top_n: int) -> list[RerankedHit]:
        """降级：按当前融合顺序输出，rerank 字段置空，截断 top_n。"""
        return degrade_to_fusion_order(scored_hits, top_n)

    @staticmethod
    def _to_hit(hit: RecallHit, rerank_score: float | None, rerank_rank: int | None) -> RerankedHit:
        """在 RecallHit 元信息上补 rerank 字段（委托 ``reranked_from_recall``，单一来源）。"""
        return reranked_from_recall(hit, rerank_score=rerank_score, rerank_rank=rerank_rank)
