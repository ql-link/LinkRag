"""召回候选融合策略。

默认策略仍是 RRF (Reciprocal Rank Fusion)。``weighted_score`` 是可选策略：
BM25 / sparse 原始分先做 ``log1p``，dense 原始分直用，再按 source 内 min-max 归一化
和配置权重融合。
"""

import math

from src.core.pipeline.recall.exceptions import RecallValidationError
from src.core.pipeline.recall.models import (
    FUSION_STRATEGY_RRF,
    FUSION_STRATEGY_WEIGHTED_SCORE,
    RecallHit,
    RetrieverHit,
    normalize_fusion_strategy,
    validate_fusion_weight,
)
from src.core.pipeline.recall.protocols import SOURCE_BM25, SOURCE_DENSE, SOURCE_SPARSE

_WEIGHTED_SCORE_SOURCES = {SOURCE_BM25, SOURCE_SPARSE, SOURCE_DENSE}


def fuse_hits(
    *,
    per_source_hits: dict[str, list[RetrieverHit]],
    all_sources: list[str],
    strategy: str,
    rrf_k: int,
    weights: dict[str, float],
) -> list[RecallHit]:
    """按指定策略融合多路召回候选。"""
    normalized_strategy = normalize_fusion_strategy(strategy)
    if normalized_strategy == FUSION_STRATEGY_RRF:
        return fuse_with_rrf(per_source_hits=per_source_hits, all_sources=all_sources, k=rrf_k)
    if normalized_strategy == FUSION_STRATEGY_WEIGHTED_SCORE:
        return fuse_with_weighted_score(
            per_source_hits=per_source_hits,
            all_sources=all_sources,
            weights=weights,
        )
    raise RecallValidationError(f"unsupported fusion strategy: {strategy!r}")


def fuse_with_rrf(
    per_source_hits: dict[str, list[RetrieverHit]],
    all_sources: list[str],
    k: int,
) -> list[RecallHit]:
    """把多路候选融合为按融合分降序的 ``RecallHit`` 列表。

    Args:
        per_source_hits: 键为 source 名，值为该路返回的已降序列表；只包含成功路。
        all_sources: 已装配的全部 source 名（含失败与返回空的路），用于在结果的
            ``scores`` 字典中为未命中的路填 ``None``，保持键集合稳定。
        k: RRF 平滑常数，业界默认 60。

    Returns:
        融合后的候选列表，按 ``fused_score`` 降序排。同一 ``chunk_id`` 在多路出
        现时分数累加，只出现在一路时也保留（分数为该路的单一贡献）。

    Note:
        pipeline 信任各路自己的排序——本函数按下标 + 1 取 rank，不重新排序输入。
    """
    accumulator: dict[str, _FusionEntry] = {}

    for source, hits in per_source_hits.items():
        for rank_zero_based, hit in enumerate(hits):
            rank = rank_zero_based + 1
            contribution = 1.0 / (k + rank)
            entry = accumulator.get(hit.chunk_id)
            if entry is None:
                entry = _FusionEntry(
                    chunk_id=hit.chunk_id,
                    doc_id=hit.doc_id,
                    dataset_id=hit.dataset_id,
                    fused_score=0.0,
                    scores={s: None for s in all_sources},
                )
                accumulator[hit.chunk_id] = entry
            entry.fused_score += contribution
            entry.scores[source] = hit.score

    fused_hits = [
        RecallHit(
            chunk_id=entry.chunk_id,
            doc_id=entry.doc_id,
            dataset_id=entry.dataset_id,
            fused_score=entry.fused_score,
            scores=entry.scores,
        )
        for entry in accumulator.values()
    ]
    fused_hits.sort(key=lambda h: h.fused_score, reverse=True)
    return fused_hits


def fuse_with_weighted_score(
    per_source_hits: dict[str, list[RetrieverHit]],
    all_sources: list[str],
    weights: dict[str, float],
) -> list[RecallHit]:
    """把多路候选按归一化原始分和权重融合为 ``RecallHit`` 列表。

    权重只按本次有命中的 active sources 归一；某个 chunk 没命中某一路时，该路贡献为 0，
    不按 chunk 自己命中的 source 再重分配。
    """
    _validate_weight_map(weights)
    active_sources = [source for source in all_sources if per_source_hits.get(source)]
    if not active_sources:
        return []
    unsupported = [source for source in active_sources if source not in _WEIGHTED_SCORE_SOURCES]
    if unsupported:
        raise RecallValidationError(
            f"weighted_score only supports bm25/sparse/dense sources, got: {unsupported}"
        )

    active_weight_sum = sum(weights[source] for source in active_sources)
    if active_weight_sum <= 0:
        raise RecallValidationError("active source fusion weight sum must be > 0")

    accumulator: dict[str, _FusionEntry] = {}
    for source in active_sources:
        normalized_by_chunk = _normalize_source_scores(source, per_source_hits[source])
        normalized_weight = weights[source] / active_weight_sum
        for hit in per_source_hits[source]:
            entry = accumulator.get(hit.chunk_id)
            if entry is None:
                entry = _FusionEntry(
                    chunk_id=hit.chunk_id,
                    doc_id=hit.doc_id,
                    dataset_id=hit.dataset_id,
                    fused_score=0.0,
                    scores={s: None for s in all_sources},
                )
                accumulator[hit.chunk_id] = entry
            entry.fused_score += normalized_by_chunk[hit.chunk_id] * normalized_weight
            entry.scores[source] = hit.score

    fused_hits = [
        RecallHit(
            chunk_id=entry.chunk_id,
            doc_id=entry.doc_id,
            dataset_id=entry.dataset_id,
            fused_score=entry.fused_score,
            scores=entry.scores,
        )
        for entry in accumulator.values()
    ]
    fused_hits.sort(key=lambda h: (-h.fused_score, h.chunk_id))
    return fused_hits


def _validate_weight_map(weights: dict[str, float]) -> None:
    for source in _WEIGHTED_SCORE_SOURCES:
        if source not in weights:
            raise RecallValidationError(f"missing fusion weight for source={source}")
        try:
            validate_fusion_weight(weights[source], field_name=f"{source}_weight")
        except ValueError as exc:
            raise RecallValidationError(str(exc)) from exc


def _normalize_source_scores(source: str, hits: list[RetrieverHit]) -> dict[str, float]:
    transformed = [(hit.chunk_id, _transform_score(source, hit.score)) for hit in hits]
    if not transformed:
        return {}
    values = [score for _chunk_id, score in transformed]
    min_score = min(values)
    max_score = max(values)
    if len(transformed) == 1 or max_score == min_score:
        return {chunk_id: 1.0 for chunk_id, _score in transformed}
    score_range = max_score - min_score
    return {chunk_id: (score - min_score) / score_range for chunk_id, score in transformed}


def _transform_score(source: str, raw_score: float) -> float:
    if not math.isfinite(raw_score):
        raise RecallValidationError(f"{source} score must be finite")
    if source in {SOURCE_BM25, SOURCE_SPARSE}:
        if raw_score < 0:
            raise RecallValidationError(f"{source} score must be >= 0 for weighted_score")
        return math.log1p(raw_score)
    if source == SOURCE_DENSE:
        return raw_score
    raise RecallValidationError(f"unsupported weighted_score source: {source}")


class _FusionEntry:
    """累积期的可变中间态；最终转成 frozen ``RecallHit``。"""

    __slots__ = ("chunk_id", "doc_id", "dataset_id", "fused_score", "scores")

    def __init__(
        self,
        chunk_id: str,
        doc_id: int,
        dataset_id: int,
        fused_score: float,
        scores: dict[str, float | None],
    ) -> None:
        self.chunk_id = chunk_id
        self.doc_id = doc_id
        self.dataset_id = dataset_id
        self.fused_score = fused_score
        self.scores = scores
