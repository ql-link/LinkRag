"""固定 weighted score 召回候选融合。

BM25 / sparse 原始分先做 ``log1p``，dense 原始分直用，再按 source 内 min-max 归一化
和配置权重融合。
"""

import math

from src.core.pipeline.recall.exceptions import RecallValidationError
from src.core.pipeline.recall.models import RecallHit, RetrieverHit, validate_fusion_weight
from src.core.pipeline.recall.protocols import SOURCE_BM25, SOURCE_DENSE, SOURCE_SPARSE

_WEIGHTED_SCORE_SOURCES = {SOURCE_BM25, SOURCE_SPARSE, SOURCE_DENSE}


def fuse_hits(
    *,
    per_source_hits: dict[str, list[RetrieverHit]],
    all_sources: list[str],
    weights: dict[str, float],
) -> list[RecallHit]:
    """按固定 weighted score 规则融合多路召回候选。"""
    return fuse_with_weighted_score(
        per_source_hits=per_source_hits,
        all_sources=all_sources,
        weights=weights,
    )


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
