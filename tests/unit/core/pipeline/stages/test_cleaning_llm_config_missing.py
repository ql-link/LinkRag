# -*- coding: utf-8 -*-
"""CleaningStage 把 Dataset 缺少必配增强快照归类为明确错误。

验证增强环节抛出的 EnhancementModelMissingError 被单独归类，
而非笼统的 PARSE_ENGINE_FAILED。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.markdown_parser import EnhancementModelMissingError
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
async def test_cleaning_classifies_enhancement_binding_missing():
    stage = _build_stage(EnhancementModelMissingError("table"))
    outcome = await stage.run(_build_ctx())

    assert outcome.ok is False
    assert outcome.failure_reason.startswith(ParseFailureCode.ENHANCEMENT_MODEL_MISSING.value)
    assert isinstance(outcome.error, EnhancementModelMissingError)


@pytest.mark.asyncio
async def test_cleaning_other_error_stays_parse_engine_failed():
    """其余异常仍归 PARSE_ENGINE_FAILED，未被新分支误吞。"""
    stage = _build_stage(RuntimeError("boom"))
    outcome = await stage.run(_build_ctx())

    assert outcome.ok is False
    assert outcome.failure_reason.startswith(ParseFailureCode.PARSE_ENGINE_FAILED.value)
