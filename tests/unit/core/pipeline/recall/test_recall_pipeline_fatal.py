# -*- coding: utf-8 -*-
"""RecallFatalError 绕过宽松降级：必备前置缺失须让整请求失败。"""
from __future__ import annotations

import pytest

from src.core.pipeline.recall import (
    RecallFatalError,
    RecallPipeline,
    RecallPipelineConfig,
    RecallRequest,
    RetrieverHit,
)

from .conftest import FakeRetriever


def _req():
    return RecallRequest(
        query="q", user_id=1, dataset_ids=[1], doc_ids=None, top_k=5
    )


@pytest.mark.asyncio
async def test_fatal_error_bypasses_lenient_degrade():
    """宽松模式下，一路抛 RecallFatalError、另一路成功 → 整请求仍抛 RecallFatalError。"""
    fatal = FakeRetriever(source="dense", exc=RecallFatalError("user embedding config missing"))
    ok = FakeRetriever(
        source="bm25",
        hits=[RetrieverHit(chunk_id="c1", doc_id=1, dataset_id=1, score=1.0, source="bm25")],
    )
    pipeline = RecallPipeline([fatal, ok], RecallPipelineConfig(strict=False))

    with pytest.raises(RecallFatalError):
        await pipeline.execute(_req())


@pytest.mark.asyncio
async def test_ordinary_failure_still_degrades_in_lenient():
    """对照组：普通异常在宽松模式下被降级，不影响其余路返回。"""
    failing = FakeRetriever(source="dense", exc=RuntimeError("qdrant timeout"))
    ok = FakeRetriever(
        source="bm25",
        hits=[RetrieverHit(chunk_id="c1", doc_id=1, dataset_id=1, score=1.0, source="bm25")],
    )
    pipeline = RecallPipeline([failing, ok], RecallPipelineConfig(strict=False))

    resp = await pipeline.execute(_req())
    assert "dense" in resp.failed_sources
    assert len(resp.hits) == 1
