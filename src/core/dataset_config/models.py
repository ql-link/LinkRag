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

from pydantic import BaseModel, field_validator


def _settings():
    from src.config import settings

    return settings


class ChunkingConfig(BaseModel):
    """分块策略配置（3 项），消费点见 ``splitter/factory.py``。

    dev 的 splitter 重写（candidate_boundary 阶段算法 + StageRouter）已移除旧 percentile
    语义切片及其 ``CHUNKING_SEMANTIC_*`` / ``CHUNKING_MIN|MAX_CHUNK_TOKENS`` /
    ``CHUNKING_MIN_DISTANCE_GATE`` 系统配置，故数据集级分块配置只保留当前架构仍生效的三项：
    标题断层级、候选分块 token 软下限、相邻 chunk overlap。后续分块算法再扩展可配项时，在此
    追加字段 + 对应 ``CHUNKING_*`` 系统默认即可。
    """

    heading_break_level: int = 5
    min_candidate_chunk_tokens: int = 128
    overlap_tokens: int = 64

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

    @classmethod
    def from_settings(cls) -> "ChunkingConfig":
        """以运行期系统 ``Settings`` 为 L1 基线构造（未配置数据集时的实际默认）。"""
        s = _settings()
        return cls(
            heading_break_level=s.CHUNKING_HEADING_BREAK_LEVEL,
            min_candidate_chunk_tokens=s.CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS,
            overlap_tokens=s.CHUNKING_OVERLAP_TOKENS,
        )


class EnhancementConfig(BaseModel):
    """Markdown 增强配置（4 项），消费点见 ``markdown_parser/orchestrator.py``。

    ``table_model`` / ``vision_model`` 是数据集为增强配置的模型名；为空且对应增强开启时
    解析任务直接失败（不回退系统兜底模型）。
    """

    enable_table_enhancement: bool = True
    enable_image_enhancement: bool = True
    table_model: str | None = None
    vision_model: str | None = None

    @classmethod
    def from_settings(cls) -> "EnhancementConfig":
        """L1 基线：开关取系统 ``MARKDOWN_PARSER_ENABLE_*``；模型名一律 ``None``。

        模型名不从系统配置 seed——按需求约定增强模型不走系统兜底，未在数据集显式配置即视为
        未配置（增强开启时直接失败）。
        """
        s = _settings()
        return cls(
            enable_table_enhancement=s.MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT,
            enable_image_enhancement=s.MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT,
            table_model=None,
            vision_model=None,
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
    """召回检索配置（6 项），消费点见 ``routes/rag.py`` 与各 retriever。"""

    recall_result_limit: int = 20
    recall_context_token_budget: int = 4000
    sparse_top_k: int = 10
    sparse_score_threshold: float = 0.0
    dense_top_k: int = 10
    dense_score_threshold: float = 0.0

    @classmethod
    def from_settings(cls) -> "RecallConfig":
        """以运行期系统 ``Settings`` 为 L1 基线构造。"""
        s = _settings()
        return cls(
            recall_result_limit=s.RECALL_RESULT_LIMIT,
            recall_context_token_budget=s.RECALL_GENERATION_CONTEXT_TOKEN_BUDGET,
            sparse_top_k=s.SPARSE_RETRIEVAL_TOP_K,
            sparse_score_threshold=s.SPARSE_RETRIEVAL_SCORE_THRESHOLD,
            dense_top_k=s.DENSE_RETRIEVAL_TOP_K,
            dense_score_threshold=s.DENSE_RETRIEVAL_SCORE_THRESHOLD,
        )


class DatasetParseConfigBundle(BaseModel):
    """一个数据集的四类配置聚合。

    ``DatasetConfigService.get_config()`` 的返回类型；消费模块各取所需。
    """

    chunking: ChunkingConfig = ChunkingConfig()
    enhancement: EnhancementConfig = EnhancementConfig()
    pdf: PDFConfig = PDFConfig()
    recall: RecallConfig = RecallConfig()

    @classmethod
    def defaults(cls) -> "DatasetParseConfigBundle":
        """全系统默认 bundle（无配置行 / 读取失败时使用），各类取运行期 ``Settings`` L1 基线。"""
        return cls(
            chunking=ChunkingConfig.from_settings(),
            enhancement=EnhancementConfig.from_settings(),
            pdf=PDFConfig.from_settings(),
            recall=RecallConfig.from_settings(),
        )
