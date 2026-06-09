"""召回后重排子包对外门面。

承接 ``RecallPipeline`` 的 RRF 后候选，回表取正文并调用用户 RERANK 模型重排，
输出保留 RRF 解释信息且带 rerank 分数/名次的顺序候选。本期独立交付，不接入召回/生成链路。
"""

from src.core.pipeline.rerank.models import (
    RerankedHit,
    RerankRequest,
    RerankResponse,
)
from src.core.pipeline.rerank.reranker import PostRecallReranker

__all__ = [
    "PostRecallReranker",
    "RerankRequest",
    "RerankResponse",
    "RerankedHit",
]
