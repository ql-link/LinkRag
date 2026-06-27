"""召回后重排子包对外门面。

承接 ``RecallPipeline`` 的融合候选，回表取正文并调用用户 RERANK 模型重排，
输出保留融合解释信息且带 rerank 分数/名次的顺序候选。已接入 ``rag/stream`` 召回后链路
（不可用时由调用方复用 ``degrade_to_fusion_order`` 降级为当前融合顺序）。
"""

from src.core.pipeline.rerank.models import (
    RerankedHit,
    RerankRequest,
    RerankResponse,
)
from src.core.pipeline.rerank.reranker import (
    PostRecallReranker,
    degrade_to_fusion_order,
    degrade_to_rrf_order,
    reranked_from_recall,
)

__all__ = [
    "PostRecallReranker",
    "RerankRequest",
    "RerankResponse",
    "RerankedHit",
    "degrade_to_fusion_order",
    "degrade_to_rrf_order",
    "reranked_from_recall",
]
