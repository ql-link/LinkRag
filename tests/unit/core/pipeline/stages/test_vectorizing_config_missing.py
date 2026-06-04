"""LINK-91：VectorizingStage 把稠密 embedder 解析异常归类为明确失败码的单测。

钉住对外契约——用户无默认 EMBEDDING 配置 / 模型维度不受支持时，发给 Java 的
failure_reason 前缀必须是 LLM_CONFIG_MISSING / EMBEDDING_DIMENSION_UNSUPPORTED，
而不是笼统的 VECTORIZING_FAILED，便于业务侧提示用户去配置。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.pipeline.parse_task.stages.vectorizing import VectorizingStage
from src.core.splitter.factory import (
    DenseEmbeddingConfigMissingError,
    DenseEmbeddingDimensionError,
)


def _stage(store_exc: Exception) -> VectorizingStage:
    services = SimpleNamespace(store_chunk_vectors=AsyncMock(side_effect=store_exc))
    return VectorizingStage(services, MagicMock(), MagicMock())


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(chunks=[object()], payload=SimpleNamespace(task_id="t1"), db=object())


@pytest.mark.asyncio
async def test_run_classifies_config_missing_as_llm_config_missing():
    stage = _stage(DenseEmbeddingConfigMissingError(7))

    outcome = await stage.run(_ctx())

    assert outcome.ok is False
    assert outcome.failure_reason.startswith("LLM_CONFIG_MISSING:")


@pytest.mark.asyncio
async def test_run_classifies_dimension_error_as_dimension_unsupported():
    stage = _stage(
        DenseEmbeddingDimensionError(
            user_id=7, model_name="m", actual_dim=1536, expected_dim=1024
        )
    )

    outcome = await stage.run(_ctx())

    assert outcome.ok is False
    assert outcome.failure_reason.startswith("EMBEDDING_DIMENSION_UNSUPPORTED:")
