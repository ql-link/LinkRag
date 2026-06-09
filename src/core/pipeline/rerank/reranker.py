"""召回后重排核心：回填正文 → 解析用户 RERANK 模型 → 调用 rerank → 映射输出 / 降级。

职责边界（brief：本期独立交付、不接入召回/生成链路）：
- 上游产出 RRF 候选、下游消费重排结果，均不在本模块——它是一个可独立调用、独立测试的单元。
- 不碰向量化、不碰 LLM 文本生成、不触 ``RecallPipeline`` 纯召回边界。

失败语义（brief Q1）：
- **未配置 RERANK 模型 → 硬失败**：解析模型的异常直接上抛，不降级（rerank 是本模块核心职责）。
- **调用失败 / 返回不可用 → 降级**：返回 RRF 顺序候选并标记 ``rerank_applied=False``。

依赖通过构造注入（``content_fetcher`` / ``model_resolver``），便于单测以替身替换 DB 与 LLM。
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from loguru import logger

from src.config import settings
from src.core.llm.user_model_resolver import ResolvedModel, aresolve_user_model
from src.core.pipeline.chunk_content import fetch_chunk_contents
from src.core.pipeline.recall.models import RecallHit
from src.core.pipeline.rerank.models import RerankedHit, RerankRequest, RerankResponse

# 注入点签名：正文回填 (chunk_ids, user_id) -> {chunk_id: 正文}
ContentFetcher = Callable[[list[str], int], Awaitable[dict[str, str]]]
# 注入点签名：按 (user_id, capability) 解析用户模型
ModelResolver = Callable[..., Awaitable[ResolvedModel]]


class PostRecallReranker:
    """承接 RRF 后候选，回表取正文并调用用户 RERANK 模型重排。"""

    def __init__(
        self,
        *,
        content_fetcher: ContentFetcher = fetch_chunk_contents,
        model_resolver: ModelResolver = aresolve_user_model,
    ) -> None:
        self._fetch = content_fetcher
        self._resolve = model_resolver

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        """对 RRF 后候选执行重排，返回重排后候选列表。

        步骤：空候选 → 回填正文 → 缺正文过滤（只记日志）→ 全空短路 →
        解析 RERANK 模型（硬失败点）→ 调用 rerank（降级点）→ index 映射 → 截断 top_n。
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

        # 正文回填：只取本用户 ACTIVE 非空正文；查不到的 chunk 不参与 rerank。
        contents = await self._fetch([h.chunk_id for h in request.hits], request.user_id)
        scored_hits = [h for h in request.hits if contents.get(h.chunk_id)]
        skipped = len(request.hits) - len(scored_hits)
        if skipped:
            # 剔除只记日志，不进返回结构（brief Q5）。
            logger.info(
                "[rerank] skipped {} chunk(s) without content user_id={}",
                skipped, request.user_id,
            )

        # 全部缺正文：等同空命中，不调模型。
        if not scored_hits:
            return _resp([], False)

        # 硬失败点：解析用户配置的 RERANK 模型，不开系统兜底。
        # 未配置 / provider 不支持 → 异常上抛，不降级。
        resolved = await self._resolve(
            user_id=request.user_id,
            capability="RERANK",
            allow_system_fallback=False,
        )

        # 按 RRF 顺序构造 rerank documents；top_n 传 None 取回全部打分项，
        # 由本模块自行映射、排序、编号、截断，保证 rerank_rank 连续可控。
        documents = [contents[h.chunk_id] for h in scored_hits]
        try:
            result = await resolved.provider.rerank(
                query=request.query,
                documents=documents,
                model=resolved.model_name,
                top_n=None,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 调用失败统一降级为 RRF 顺序
            logger.warning(
                "[rerank] model call failed, degrade to RRF order user_id={}: {}",
                request.user_id, exc,
            )
            return _resp(self._degrade(scored_hits, top_n), False)

        ranked = self._map_results(scored_hits, result)
        if ranked is None:
            # 返回不完整（无任一合法 index）→ 降级。
            logger.warning(
                "[rerank] unusable rerank indices, degrade to RRF order user_id={}",
                request.user_id,
            )
            return _resp(self._degrade(scored_hits, top_n), False)

        return _resp(ranked[:top_n], True)

    def _map_results(self, scored_hits: list[RecallHit], result) -> list[RerankedHit] | None:
        """把 rerank 返回的 (index, score) 映射回候选，健壮处理越界/重复/缺失。

        - 过滤越界 index、去重重复 index（保留首次出现）。
        - 无任一合法 index → 返回 None（触发降级）。
        - 合法项按 rerank_score 降序编号；未被任何合法 index 命中的有正文候选，
          按 RRF 顺序追加为「无分 tail」（rerank_score=None），不丢候选。
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
        # 无分 tail：未返回的有正文候选按 RRF 顺序追加，rerank_score=None。
        for i, hit in enumerate(scored_hits):
            if i not in seen:
                ranked.append(self._to_hit(hit, None, rank))
                rank += 1
        return ranked

    def _degrade(self, scored_hits: list[RecallHit], top_n: int) -> list[RerankedHit]:
        """降级：按 RRF 顺序（scored_hits 已是 RRF 序）输出，rerank 字段置空，截断 top_n。"""
        return [self._to_hit(hit, None, None) for hit in scored_hits[:top_n]]

    @staticmethod
    def _to_hit(
        hit: RecallHit, rerank_score: float | None, rerank_rank: int | None
    ) -> RerankedHit:
        """在 RecallHit 元信息上补 rerank 字段，保留 fused_score 与各路 scores。"""
        return RerankedHit(
            chunk_id=hit.chunk_id,
            doc_id=hit.doc_id,
            dataset_id=hit.dataset_id,
            fused_score=hit.fused_score,
            scores=hit.scores,
            rerank_score=rerank_score,
            rerank_rank=rerank_rank,
        )
