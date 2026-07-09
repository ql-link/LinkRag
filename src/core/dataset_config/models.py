# -*- coding: utf-8 -*-
"""数据集级解析/检索配置的 Pydantic 模型。

四类配置（分块 / Markdown 增强 / PDF / 召回）各对应一个模型。

**分层合并语义**：系统级 ``Settings`` 是 L1 fallback，数据集级 JSON 在其上覆盖。每个模型的
静态字段默认值与 ``Settings`` 对应项一致（作为 schema 兜底），但实际生效的 L1 取**运行期**
``Settings`` 值——见各模型的 :meth:`from_settings`。:class:`DatasetConfigService` 以
``from_settings()`` 为基线、叠加数据集 JSON 覆盖字段，因此运维通过环境变量改了系统级
``CHUNKING_*`` / ``RECALL_*`` 等，未配置数据集仍会跟随生效（不是被这里的静态默认值锁死）。
"""

from __future__ import annotations

import math

from pydantic import BaseModel, field_validator, model_validator

SUPPORTED_RECALL_FUSION_STRATEGIES = frozenset({"rrf", "weighted_score"})
SUPPORTED_STAGE_TWO_ALGORITHMS = frozenset({"noop", "semantic_depth_window"})


def _settings():
    from src.config import settings

    return settings


class ChunkingConfig(BaseModel):
    """分块策略配置（3 项），消费点见 ``splitter/factory.py``。

    当前数据集级分块配置只保留 splitter 主链路仍生效的三项：标题断层级、候选分块 token
    软下限、相邻 chunk overlap。后续分块算法再扩展可配项时，在此追加字段 + 对应
    ``CHUNKING_*`` 系统默认即可。
    """

    heading_break_level: int = 5
    min_candidate_chunk_tokens: int = 128
    overlap_tokens: int = 64
    max_chunk_tokens: int = 512
    hard_max_tokens: int = 1024
    stage_two_algorithm: str = "noop"
    protected_neighbor_overlap: bool = False

    @field_validator("overlap_tokens")
    @classmethod
    def _validate_overlap_tokens(cls, v: int) -> int:
        if v < 0 or v > 64:
            raise ValueError("overlap_tokens must be between 0 and 64")
        return v

    @field_validator("min_candidate_chunk_tokens")
    @classmethod
    def _validate_min_candidate_chunk_tokens(cls, v: int) -> int:
        if v < 128 or v > 256:
            raise ValueError("min_candidate_chunk_tokens must be between 128 and 256")
        return v

    @field_validator("max_chunk_tokens")
    @classmethod
    def _validate_max_chunk_tokens(cls, v: int) -> int:
        if v < 256 or v > 2048:
            raise ValueError("max_chunk_tokens must be between 256 and 2048")
        return v

    @field_validator("hard_max_tokens")
    @classmethod
    def _validate_hard_max_tokens(cls, v: int) -> int:
        if v < 512 or v > 8192:
            raise ValueError("hard_max_tokens must be between 512 and 8192")
        return v

    @field_validator("stage_two_algorithm")
    @classmethod
    def _validate_stage_two_algorithm(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in SUPPORTED_STAGE_TWO_ALGORITHMS:
            supported = ", ".join(sorted(SUPPORTED_STAGE_TWO_ALGORITHMS))
            raise ValueError(f"stage_two_algorithm must be one of: {supported}")
        return normalized

    @model_validator(mode="before")
    @classmethod
    def _validate_token_bounds_before(cls, data):
        if not isinstance(data, dict):
            return data

        def resolve_int(name: str) -> int | None:
            if name not in data:
                return None
            try:
                return int(data[name])
            except (TypeError, ValueError):
                return None

        min_candidate = resolve_int("min_candidate_chunk_tokens")
        max_chunk = resolve_int("max_chunk_tokens")
        hard_max = resolve_int("hard_max_tokens")
        if min_candidate is not None and max_chunk is not None and max_chunk < min_candidate:
            raise ValueError("max_chunk_tokens must be >= min_candidate_chunk_tokens")
        if hard_max is not None and max_chunk is not None and hard_max < max_chunk:
            raise ValueError("hard_max_tokens must be >= max_chunk_tokens")
        return data

    @model_validator(mode="after")
    def _validate_token_bounds(self) -> "ChunkingConfig":
        if self.max_chunk_tokens < self.min_candidate_chunk_tokens:
            raise ValueError("max_chunk_tokens must be >= min_candidate_chunk_tokens")
        if self.hard_max_tokens < self.max_chunk_tokens:
            raise ValueError("hard_max_tokens must be >= max_chunk_tokens")
        return self

    @classmethod
    def from_settings(cls) -> "ChunkingConfig":
        """以运行期系统 ``Settings`` 为 L1 基线构造（未配置数据集时的实际默认）。"""
        s = _settings()
        return cls(
            heading_break_level=s.CHUNKING_HEADING_BREAK_LEVEL,
            min_candidate_chunk_tokens=s.CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS,
            overlap_tokens=s.CHUNKING_OVERLAP_TOKENS,
            max_chunk_tokens=s.CHUNKING_MAX_CHUNK_TOKENS,
            hard_max_tokens=s.CHUNKING_HARD_MAX_TOKENS,
            stage_two_algorithm=s.CHUNKING_STAGE_TWO_ALGORITHM,
            protected_neighbor_overlap=s.CHUNKING_PROTECTED_NEIGHBOR_OVERLAP,
        )


class EnhancementConfig(BaseModel):
    """Markdown 增强配置（2 项：表格 / 图片增强开关），消费点见 ``markdown_parser/orchestrator.py``。

    数据集层只配置「是否开启」，**不再选择增强模型**：增强使用的模型统一取发起用户该能力
    （表格→CHAT，图片→VISION）的默认 LLM 配置。开启对应增强但用户未配置该能力默认模型时，
    解析任务直接失败（:class:`EnhancementModelMissingError` → ``ENHANCEMENT_MODEL_MISSING``），
    不回退系统兜底模型。

    历史数据 / 旧 JSON 中可能残留 ``table_model`` / ``vision_model`` 字段，Pydantic 默认忽略
    多余键，反序列化不受影响。
    """

    enable_table_enhancement: bool = True
    enable_image_enhancement: bool = True
    enable_heading_hierarchy: bool = False

    @classmethod
    def from_settings(cls) -> "EnhancementConfig":
        """L1 基线：开关取系统 ``MARKDOWN_PARSER_ENABLE_*``。"""
        s = _settings()
        return cls(
            enable_table_enhancement=s.MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT,
            enable_image_enhancement=s.MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT,
            enable_heading_hierarchy=s.MARKDOWN_PARSER_ENABLE_HEADING_HIERARCHY,
        )


class PDFConfig(BaseModel):
    """PDF 解析配置（1 项），消费点见 ``stages/services.py:parse_file()``。

    ``pdf_parser_backend`` 为 ``None`` 表示该数据集未指定后端，由消费侧回退到
    ``settings.PDF_PARSER_BACKEND``。
    """

    pdf_parser_backend: str | None = None

    @classmethod
    def from_settings(cls) -> "PDFConfig":
        """L1 基线：``pdf_parser_backend`` 保持 ``None``。

        消费侧（``parse_file``）按 ``payload > 数据集配置 > settings.PDF_PARSER_BACKEND`` 三层
        选取，故此处无需 seed 系统值——None 即"未在数据集层指定"。
        """
        return cls(pdf_parser_backend=None)


class RecallConfig(BaseModel):
    """召回检索配置（15 项），消费点见 ``routes/rag.py`` / ``routes/recall.py`` 与各 retriever。

    其中多项为 pipeline / rerank 级旋钮：

    - ``recall_enabled_sources``：启用哪几条召回路并参与融合（``bm25`` / ``sparse`` / ``dense``）。
      **只能在系统已装配的召回路（``RECALL_ENABLED_SOURCES``）子集内收窄**：列出的路里凡未被
      系统装配的会被忽略；若交集为空则回退到系统全部已装配路（见 ``RecallPipeline`` 执行期处理）。
    - ``recall_fusion_strategy``：候选融合策略，默认 ``rrf``，可选 ``weighted_score``。
    - ``rrf_k``：RRF rank constant，仅 ``recall_fusion_strategy=rrf`` 时使用。
    - ``fusion_*_weight``：``weighted_score`` 三路权重，单项允许为 0；active source 权重和为 0
      在运行期拒绝。
    - ``rerank_top_n``：重排后返回候选条数上限（透传给 ``RerankRequest.top_n``）。
    - ``recall_strict``：召回容错模式（透传给 ``RecallRequest.strict_override``）。``True`` 时任一路
      失败即整体抛错，``False`` 时允许单路失败降级。
    """

    recall_result_limit: int = 64
    recall_context_token_budget: int = 4000
    bm25_top_k: int = 100
    sparse_top_k: int = 50
    sparse_score_threshold: float = 0.0
    dense_top_k: int = 100
    dense_score_threshold: float = 0.0
    recall_enabled_sources: list[str] = ["bm25", "sparse", "dense"]
    recall_fusion_strategy: str = "rrf"
    rrf_k: int = 60
    fusion_bm25_weight: float = 0.2
    fusion_sparse_weight: float = 0.3
    fusion_dense_weight: float = 0.5
    rerank_top_n: int = 8
    recall_strict: bool = False

    @field_validator(
        "recall_result_limit",
        "bm25_top_k",
        "sparse_top_k",
        "dense_top_k",
        "rrf_k",
        "rerank_top_n",
    )
    @classmethod
    def _validate_positive_int(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be a positive int")
        return v

    @field_validator("recall_enabled_sources")
    @classmethod
    def _validate_recall_enabled_sources(cls, v: list[str]) -> list[str]:
        # 去空白 / 去空项；允许空列表（执行期回退系统全部已装配路），但不允许出现空白源名。
        cleaned = [s.strip() for s in v if s and s.strip()]
        return cleaned

    @field_validator("recall_fusion_strategy")
    @classmethod
    def _validate_recall_fusion_strategy(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in SUPPORTED_RECALL_FUSION_STRATEGIES:
            supported = ", ".join(sorted(SUPPORTED_RECALL_FUSION_STRATEGIES))
            raise ValueError(f"recall_fusion_strategy must be one of: {supported}")
        return normalized

    @field_validator("fusion_bm25_weight", "fusion_sparse_weight", "fusion_dense_weight")
    @classmethod
    def _validate_recall_fusion_weight(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0:
            raise ValueError("fusion weights must be finite floats >= 0")
        return v

    @classmethod
    def from_settings(cls) -> "RecallConfig":
        """以运行期系统 ``Settings`` 为 L1 基线构造。"""
        s = _settings()
        return cls(
            recall_result_limit=s.RECALL_RESULT_LIMIT,
            recall_context_token_budget=s.RECALL_GENERATION_CONTEXT_TOKEN_BUDGET,
            bm25_top_k=s.RECALL_BM25_TOP_K,
            sparse_top_k=s.RECALL_SPARSE_TOP_K,
            sparse_score_threshold=s.SPARSE_RETRIEVAL_SCORE_THRESHOLD,
            dense_top_k=s.RECALL_DENSE_TOP_K,
            dense_score_threshold=s.DENSE_RETRIEVAL_SCORE_THRESHOLD,
            recall_enabled_sources=[
                src.strip() for src in (s.RECALL_ENABLED_SOURCES or "").split(",") if src.strip()
            ],
            recall_fusion_strategy=s.RECALL_FUSION_STRATEGY,
            rrf_k=s.RECALL_RRF_K,
            fusion_bm25_weight=s.RECALL_FUSION_BM25_WEIGHT,
            fusion_sparse_weight=s.RECALL_FUSION_SPARSE_WEIGHT,
            fusion_dense_weight=s.RECALL_FUSION_DENSE_WEIGHT,
            rerank_top_n=s.RERANK_DEFAULT_TOP_N,
            recall_strict=s.RECALL_STRICT_DEFAULT,
        )


class VectorModelBindingConfig(BaseModel):
    """数据集绑定的向量模型配置 ID。

    四个字段（ID + source）共同定位 Java 库的模型配置。``source=USER`` 时 ID 指向
    ``llm_user_config.id``，``source=SYSTEM`` 时指向 ``llm_system_preset.id``。Python 侧
    不在此模型中校验配置行有效性，只承载绑定信息；解析/召回消费点会按能力分别精确读取并校验。
    """

    sparse_embedding_config_id: int | None = None
    sparse_embedding_config_source: str = "USER"
    dense_embedding_config_id: int | None = None
    dense_embedding_config_source: str = "USER"


class DatasetParseConfigBundle(BaseModel):
    """一个数据集的四类配置聚合。

    ``DatasetConfigService.get_config()`` 的返回类型；消费模块各取所需。
    """

    chunking: ChunkingConfig = ChunkingConfig()
    enhancement: EnhancementConfig = EnhancementConfig()
    pdf: PDFConfig = PDFConfig()
    recall: RecallConfig = RecallConfig()
    vector_models: VectorModelBindingConfig = VectorModelBindingConfig()

    @classmethod
    def defaults(cls) -> "DatasetParseConfigBundle":
        """全系统默认 bundle（无配置行 / 读取失败时使用），各类取运行期 ``Settings`` L1 基线。"""
        return cls(
            chunking=ChunkingConfig.from_settings(),
            enhancement=EnhancementConfig.from_settings(),
            pdf=PDFConfig.from_settings(),
            recall=RecallConfig.from_settings(),
            vector_models=VectorModelBindingConfig(),
        )
