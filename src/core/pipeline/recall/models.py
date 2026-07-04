"""召回 pipeline 数据模型。

包含两类 hit：
- ``RetrieverHit``：单路返回的原始候选，pipeline 内部消费；
- ``RecallHit``：融合后对外输出的候选，含融合分与每路原始分。

不包含 chunk 正文字段（content/text/body）——召回阶段只返回 chunk_id 与元信息，
正文留给下游 reranker / 上下文拼装阶段按需反查 MySQL。
"""

import math
from dataclasses import dataclass

FUSION_STRATEGY_RRF = "rrf"
FUSION_STRATEGY_WEIGHTED_SCORE = "weighted_score"
SUPPORTED_FUSION_STRATEGIES = frozenset({FUSION_STRATEGY_RRF, FUSION_STRATEGY_WEIGHTED_SCORE})
SOURCE_MODE_HYBRID = "hybrid"
SOURCE_MODE_BM25_ONLY = "bm25_only"
SOURCE_MODE_MISSING_SPARSE = "missing_sparse"
SOURCE_MODE_MISSING_DENSE = "missing_dense"


def normalize_fusion_strategy(value: str, *, field_name: str = "fusion_strategy") -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_FUSION_STRATEGIES:
        supported = ", ".join(sorted(SUPPORTED_FUSION_STRATEGIES))
        raise ValueError(f"{field_name} must be one of: {supported}")
    return normalized


def validate_fusion_weight(value: float, *, field_name: str) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite float >= 0") from exc
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field_name} must be a finite float >= 0")
    return normalized


def validate_rrf_k(value: int, *, field_name: str = "rrf_k") -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive int") from exc
    if normalized <= 0:
        raise ValueError(f"{field_name} must be a positive int")
    return normalized


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
        fused_score: 当前融合策略产出的融合得分。
        scores: 每一路原始打分；未命中的路填 ``None``，键集合等于本次生效的 source 名。
    """

    chunk_id: str
    doc_id: int
    dataset_id: int
    fused_score: float
    scores: dict[str, float | None]


@dataclass(frozen=True)
class RecallDiagnostics:
    """召回来源结构诊断。

    ``source_mode`` 只覆盖 LINK-195 冻结的四类三路 hybrid 场景；未启用完整三路或
    无法归入四态的组合不生成 diagnostics，由现有 hits / failed_sources 语义承接。
    """

    source_mode: str
    degraded: bool
    active_sources: list[str]
    per_source_counts: dict[str, int]
    empty_sources: list[str]
    failed_sources: list[str]


def build_recall_diagnostics(
    *,
    active_sources: list[str],
    per_source_counts: dict[str, int],
    failed_sources: list[str],
) -> RecallDiagnostics | None:
    """按三路来源贡献构造 LINK-195 诊断信号。

    只在 ``bm25`` / ``sparse`` / ``dense`` 三路都实际启用时生成诊断，避免把配置
    未启用误读为召回缺失。三路全空或 vector-only 不属于本 issue 冻结的四态，保持为
    ``None``，由现有空召回语义处理。
    """
    from src.core.pipeline.recall.protocols import SOURCE_BM25, SOURCE_DENSE, SOURCE_SPARSE

    required_sources = {SOURCE_BM25, SOURCE_SPARSE, SOURCE_DENSE}
    if not required_sources.issubset(set(active_sources)):
        return None

    failed_set = set(failed_sources)
    has_bm25 = per_source_counts.get(SOURCE_BM25, 0) > 0
    has_sparse = per_source_counts.get(SOURCE_SPARSE, 0) > 0
    has_dense = per_source_counts.get(SOURCE_DENSE, 0) > 0

    if has_bm25 and has_sparse and has_dense:
        source_mode = SOURCE_MODE_HYBRID
    elif has_bm25 and not has_sparse and not has_dense:
        source_mode = SOURCE_MODE_BM25_ONLY
    elif has_bm25 and not has_sparse and has_dense:
        source_mode = SOURCE_MODE_MISSING_SPARSE
    elif has_bm25 and has_sparse and not has_dense:
        source_mode = SOURCE_MODE_MISSING_DENSE
    else:
        return None

    empty_sources = [
        source
        for source in active_sources
        if per_source_counts.get(source, 0) == 0 and source not in failed_set
    ]
    return RecallDiagnostics(
        source_mode=source_mode,
        degraded=source_mode != SOURCE_MODE_HYBRID,
        active_sources=list(active_sources),
        per_source_counts=dict(per_source_counts),
        empty_sources=empty_sources,
        failed_sources=list(failed_sources),
    )


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
        top_k: 融合后候选池上限，即 rerank 输入窗口；必须为正整数。由服务端配置决定
            （数据集级 ``recall_result_limit``，无数据集配置时回退 ``RECALL_RESULT_LIMIT``），
            不作为外部请求字段。本字段不再作为各路执行期 top_k。
        bm25_top_k: BM25 路执行期召回规模上限；来自数据集级 ``recall_config.bm25_top_k``。
        sparse_top_k: 稀疏路执行期召回规模上限；来自数据集级 ``recall_config.sparse_top_k``。
        dense_top_k: 稠密路执行期召回规模上限；来自数据集级 ``recall_config.dense_top_k``。
        sparse_score_threshold_override: 可选稀疏路分数阈值覆盖；``None`` 时 sparse 路沿用
            装配期注入的默认阈值。来自数据集级 ``recall_config.sparse_score_threshold``。
        dense_score_threshold_override: 可选稠密路分数阈值覆盖；``None`` 时 dense 路沿用
            装配期注入的默认阈值。来自数据集级 ``recall_config.dense_score_threshold``。
        enabled_sources: 可选「本次启用哪几条召回路」。``None`` / 空列表表示用全部已装配路；
            非空时**只在已装配路集合内收窄**——列出的未装配路被忽略，交集为空则回退全部已装配路。
            来自数据集级 ``recall_config.recall_enabled_sources``。
        strict_override: 可选容错模式覆盖；``None`` 时沿用 pipeline 装配期 ``RecallPipelineConfig.strict``。
            来自数据集级 ``recall_config.recall_strict``。
        fusion_strategy_override: 可选融合策略覆盖；``None`` 时沿用 pipeline 装配期
            ``RecallPipelineConfig.fusion_strategy``。来自数据集级
            ``recall_config.recall_fusion_strategy``，不来自 HTTP 请求体。
        fusion_*_weight_override: 可选三路融合权重覆盖；``None`` 时沿用 pipeline 装配期默认值。
            仅 ``weighted_score`` 使用，来自数据集级 ``recall_config``。
        rrf_k_override: 可选 RRF rank constant 覆盖；``None`` 时沿用 pipeline 装配期默认值。
            仅 ``rrf`` 使用，来自数据集级 ``recall_config.rrf_k``。
    """

    query: str
    user_id: int
    dataset_ids: list[int]
    doc_ids: list[int] | None = None
    top_k: int = 64
    bm25_top_k: int = 100
    sparse_top_k: int = 50
    dense_top_k: int = 100
    sparse_score_threshold_override: float | None = None
    dense_score_threshold_override: float | None = None
    enabled_sources: list[str] | None = None
    strict_override: bool | None = None
    fusion_strategy_override: str | None = None
    fusion_bm25_weight_override: float | None = None
    fusion_sparse_weight_override: float | None = None
    fusion_dense_weight_override: float | None = None
    rrf_k_override: int | None = None


@dataclass
class RecallResponse:
    """召回 pipeline 出参。

    Attributes:
        query: 回显原始 query。
        hits: 融合后的候选列表，按 ``fused_score`` 降序。
        per_source_counts: 各路返回的命中数；键集合 = 已装配的全部 source 名；
            失败路与返回空列表的路都计 0。
        failed_sources: 抛异常的路（按构造顺序）；返回空列表的路不入此名单。
        elapsed_ms: 整体耗时（毫秒）。
        recall_diagnostics: 三路 hybrid 来源结构诊断；非 LINK-195 四态场景可为空。
    """

    query: str
    hits: list[RecallHit]
    per_source_counts: dict[str, int]
    failed_sources: list[str]
    elapsed_ms: int
    recall_diagnostics: RecallDiagnostics | None = None


@dataclass(frozen=True)
class RecallPipelineConfig:
    """pipeline 级配置（装配期一次性指定）。

    Attributes:
        parallel: 是否并行触发各路；默认 True；False 时按 retrievers 构造顺序串行。
        strict: 严格容错；True 时任一路异常立即抛 ``RecallError``。
        rrf_k: RRF 平滑常数；业界默认 60。
        fusion_strategy: 融合策略；默认 ``rrf``。
        fusion_*_weight: ``weighted_score`` 三路权重；单项允许为 0。
    """

    parallel: bool = True
    strict: bool = False
    rrf_k: int = 60
    fusion_strategy: str = FUSION_STRATEGY_RRF
    fusion_bm25_weight: float = 0.2
    fusion_sparse_weight: float = 0.3
    fusion_dense_weight: float = 0.5

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "fusion_strategy",
            normalize_fusion_strategy(self.fusion_strategy),
        )
        object.__setattr__(self, "rrf_k", validate_rrf_k(self.rrf_k))
        for field_name in (
            "fusion_bm25_weight",
            "fusion_sparse_weight",
            "fusion_dense_weight",
        ):
            object.__setattr__(
                self,
                field_name,
                validate_fusion_weight(getattr(self, field_name), field_name=field_name),
            )
