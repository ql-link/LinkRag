# -*- coding: utf-8 -*-
"""
md_parser — Markdown 解析独立模块

从 RAGFlow 项目中提炼的 Markdown 解析逻辑，仅关注解析（Parse），
不涉及分片（Chunk）。

公开 API:
    MarkdownParser  — 主入口，组合所有解析步骤
    MarkdownScanner — 逐行扫描器
    TableExtractor  — 表格提取器
    ImageExtractor  — 图片引用提取器
    ElementType     — 元素类型枚举
    MarkdownElement — 扁平元素数据模型
    ImageRef        — 图片引用数据模型
    ParseResult     — 解析结果数据模型
    VisionClient    — 视觉处理客户端基类
    ImageDescriber  — 图片多模态集成器
    TableClient     — 大语言模型表格处理客户端基类
    TableDescriber  — 表格概括描述集成器
"""

from .heading_hierarchy import (
    GateDecision,
    HeadingGateReason,
    HeadingHierarchyConfig,
    HeadingHierarchyProcessor,
    HeadingHierarchyResult,
    HeadingInsertion,
    HeadingPlan,
    HeadingPlanGenerationError,
    HeadingPlanGenerator,
    HeadingPlanValidationError,
    LLMHeadingPlanGenerator,
    NoopHeadingPlanGenerator,
    apply_heading_plan,
    build_heading_plan_generator,
    parse_heading_plan_response,
    validate_heading_plan,
)
from .image_extractor import ImageExtractor
from .llm_integration import ImageDescriber, TableClient, TableDescriber, VisionClient
from .models import ElementType, ImageRef, MarkdownElement, ParseResult
from .orchestrator import MarkdownEnhancementOrchestrator
from .parser import MarkdownParser
from .provider_clients import (
    EnhancementModelMissingError,
    ProviderTableClient,
    ProviderVisionClient,
    abuild_table_client,
    abuild_vision_client,
)
from .scanner import MarkdownScanner

__all__ = [
    "MarkdownParser",
    "MarkdownScanner",
    "ImageExtractor",
    "ElementType",
    "MarkdownElement",
    "ImageRef",
    "ParseResult",
    "VisionClient",
    "ImageDescriber",
    "TableClient",
    "TableDescriber",
    "ProviderTableClient",
    "ProviderVisionClient",
    "EnhancementModelMissingError",
    "abuild_table_client",
    "abuild_vision_client",
    "MarkdownEnhancementOrchestrator",
    "GateDecision",
    "HeadingGateReason",
    "HeadingHierarchyConfig",
    "HeadingHierarchyProcessor",
    "HeadingHierarchyResult",
    "HeadingInsertion",
    "HeadingPlan",
    "HeadingPlanGenerationError",
    "HeadingPlanGenerator",
    "HeadingPlanValidationError",
    "LLMHeadingPlanGenerator",
    "NoopHeadingPlanGenerator",
    "apply_heading_plan",
    "build_heading_plan_generator",
    "parse_heading_plan_response",
    "validate_heading_plan",
]
