# -*- coding: utf-8 -*-
"""LINK-75：CleaningStage 把「用户缺必配 CHAT 配置」归类为 LLM_CONFIG_MISSING。

验证增强环节抛出的 LLMConfigMissingError 穿透 cleaning 的 parse 容错，被单独归类为
ParseFailureCode.LLM_CONFIG_MISSING，而非笼统的 PARSE_ENGINE_FAILED。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.markdown_parser import LLMConfigMissingError
from src.core.pipeline.parse_task.error_codes import ParseFailureCode
from src.core.pipeline.parse_task.stages.cleaning import CleaningStage
from src.core.pipeline.parse_task.stages.context import StageContext


def _build_stage(parse_file_side_effect):
    services = MagicMock()
    # 跳过源文件下载，直奔解析分支（source_path=None）。
    services.source_io.should_skip_source_download.return_value = True
    services.parse_file = AsyncMock(side_effect=parse_file_side_effect)
    return CleaningStage(
        services,
        repository=MagicMock(),
        notifier=MagicMock(),
        log_repository=MagicMock(),
    )


def _build_ctx():
    payload = MagicMock()
    payload.task_id = "task-1"
    payload.is_markdown_passthrough = False
    return StageContext(
        payload=payload,
        log_record=MagicMock(),
        pipeline_record=MagicMock(),
        db=MagicMock(),
    )


@pytest.mark.asyncio
async def test_cleaning_classifies_llm_config_missing():
    """parse_file 抛 LLMConfigMissingError → 归类为 LLM_CONFIG_MISSING。"""
    stage = _build_stage(LLMConfigMissingError("CHAT", 7))
    outcome = await stage.run(_build_ctx())

    assert outcome.ok is False
    assert outcome.failure_reason.startswith(ParseFailureCode.LLM_CONFIG_MISSING.value)
    assert isinstance(outcome.error, LLMConfigMissingError)


@pytest.mark.asyncio
async def test_cleaning_other_error_stays_parse_engine_failed():
    """其余异常仍归 PARSE_ENGINE_FAILED，未被新分支误吞。"""
    stage = _build_stage(RuntimeError("boom"))
    outcome = await stage.run(_build_ctx())

    assert outcome.ok is False
    assert outcome.failure_reason.startswith(ParseFailureCode.PARSE_ENGINE_FAILED.value)
