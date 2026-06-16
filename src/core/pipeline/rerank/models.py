"""召回后重排模块数据模型。

- :class:`RerankRequest`：入参——query、user_id、RRF 后候选列表与可选 top_n。
- :class:`RerankedHit`：出参单项——在 ``RecallHit`` 元信息基础上补 rerank 分数与名次，
  保留 RRF 解释信息（fused_score / 各路 scores）。
- :class:`RerankResponse`：出参——重排后候选列表 + 是否实际生效（降级时为 False）。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.pipeline.recall.models import RecallHit


@dataclass(frozen=True)
class RerankRequest:
    """重排入参。

    Attributes:
        query: 用户原始查询文本，与候选正文一起送入 rerank 模型。
        user_id: 发起用户身份；用于按本人 + ACTIVE 过滤回填正文、解析用户 RERANK 模型。
        hits: RRF 融合后候选（``RecallHit``，按 fused_score 降序，不含正文）。
        top_n: 重排后返回条数上限；``None`` 时取 ``settings.RERANK_DEFAULT_TOP_N``，
            显式传入时必须为正整数（``<= 0`` 由 reranker 入口拒绝）。
        contents: 可选的预回填正文 ``{chunk_id: 正文}``。调用方若已批量回填（如召回后
            生成链路），传入此字段令 reranker **复用**而不再自查库，避免对同批 chunk 重复
            回填；``None`` 时 reranker 用注入的 ``content_fetcher`` 自行回填（独立调用场景）。
    """

    query: str
    user_id: int
    hits: list[RecallHit]
    top_n: int | None = None
    contents: dict[str, str] | None = None


@dataclass(frozen=True)
class RerankedHit:
    """重排后单个候选。

    在原 ``RecallHit`` 元信息上补 rerank 字段。降级（rerank 未生效）或某候选未拿到
    rerank 分数时，``rerank_score`` / ``rerank_rank`` 为 ``None``。

    Attributes:
        chunk_id / doc_id / dataset_id: chunk 元信息，原样保留。
        fused_score: RRF 融合得分，原样保留。
        scores: 各路原始打分，原样保留。
        rerank_score: rerank 模型相关性分；降级或无分时为 None。
        rerank_rank: 重排名次（从 1 连续编号）；降级时为 None。
    """

    chunk_id: str
    doc_id: int
    dataset_id: int
    fused_score: float
    scores: dict[str, float | None]
    rerank_score: float | None
    rerank_rank: int | None


@dataclass
class RerankResponse:
    """重排出参。

    Attributes:
        query: 回显原始 query。
        hits: 重排后候选列表；rerank 生效时按 rerank_score 降序，降级时为 RRF 顺序。
        rerank_applied: rerank 是否实际生效；调用失败 / 返回不可用时降级为 False。
        elapsed_ms: 整体耗时（毫秒）。
    """

    query: str
    hits: list[RerankedHit]
    rerank_applied: bool
    elapsed_ms: int
