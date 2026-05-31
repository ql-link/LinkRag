"""RRF (Reciprocal Rank Fusion) 粗融合。

为什么用 RRF 不直接加分：三路打分物理意义各异（余弦相似度 / 稀疏点积 / BM25），
数值范围天差地别，直接相加或归一化都会引入伪精度。RRF 只依赖排名信息，对各路
打分尺度不敏感，是召回阶段融合的事实标准。
"""

from src.core.pipeline.recall.models import RecallHit, RetrieverHit


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
