"""召回 pipeline 数据模型。

包含两类 hit：
- ``RetrieverHit``：单路返回的原始候选，pipeline 内部消费；
- ``RecallHit``：RRF 融合后对外输出的候选，含融合分与每路原始分。

不包含 chunk 正文字段（content/text/body）——召回阶段只返回 chunk_id 与元信息，
正文留给下游 reranker / 上下文拼装阶段按需反查 MySQL。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrieverHit:
    """单路召回返回的原始候选。

    Attributes:
        chunk_id: chunk 唯一标识，必须以 MySQL ``kb_document_chunk.chunk_id`` 为锚点。
        doc_id: chunk 所属文档 id。
        dataset_id: chunk 所属数据集 id。
        score: 该路原始打分（余弦相似度 / 稀疏点积 / BM25 等，物理意义各异）。
        source: 标识来自哪一路，如 ``"dense"`` / ``"sparse"`` / ``"bm25"``。
    """

    chunk_id: str
    doc_id: int
    dataset_id: int
    score: float
    source: str


@dataclass(frozen=True)
class RecallHit:
    """融合后的对外候选。

    Attributes:
        chunk_id: chunk 唯一标识。
        doc_id: chunk 所属文档 id。
        dataset_id: chunk 所属数据集 id。
        fused_score: RRF 融合得分（已装配的所有命中路 ``1/(k+rank)`` 之和）。
        scores: 每一路原始打分；未命中的路填 ``None``，键集合等于已装配的全部 source 名。
    """

    chunk_id: str
    doc_id: int
    dataset_id: int
    fused_score: float
    scores: dict[str, float | None]


@dataclass(frozen=True)
class RecallRequest:
    """召回 pipeline 入参。

    Attributes:
        query: 用户原始查询文本，必须非空非纯空白。
        user_id: 发起召回的用户身份，必须为正整数。由调用方在请求期确定
            （HTTP 入口从内部凭证 claims 注入），pipeline 执行期透传给各路 retriever，
            不再在 retriever 装配期注入——便于 pipeline 单例化与按用户审计/隔离。
        dataset_ids: 数据集范围，**允许空列表**（表示不限数据集做全库召回，
            调用方自行保证身份合法）。
        doc_ids: 可选文档过滤；不传或 ``None`` 表示不限。
        top_k: 各路执行期召回规模上限，同时作为融合后结果的截断上限；必须为正整数。
            由服务端配置（``RECALL_RESULT_LIMIT``）决定，不作为外部请求字段。
    """

    query: str
    user_id: int
    dataset_ids: list[int]
    doc_ids: list[int] | None = None
    top_k: int = 20


@dataclass
class RecallResponse:
    """召回 pipeline 出参。

    Attributes:
        query: 回显原始 query。
        hits: RRF 融合后的候选列表，按 ``fused_score`` 降序。
        per_source_counts: 各路返回的命中数；键集合 = 已装配的全部 source 名；
            失败路与返回空列表的路都计 0。
        failed_sources: 抛异常的路（按构造顺序）；返回空列表的路不入此名单。
        elapsed_ms: 整体耗时（毫秒）。
    """

    query: str
    hits: list[RecallHit]
    per_source_counts: dict[str, int]
    failed_sources: list[str]
    elapsed_ms: int


@dataclass(frozen=True)
class RecallPipelineConfig:
    """pipeline 级配置（装配期一次性指定）。

    Attributes:
        parallel: 是否并行触发各路；默认 True；False 时按 retrievers 构造顺序串行。
        strict: 严格容错；True 时任一路异常立即抛 ``RecallError``。
        rrf_k: RRF 平滑常数；业界默认 60。
    """

    parallel: bool = True
    strict: bool = False
    rrf_k: int = 60
