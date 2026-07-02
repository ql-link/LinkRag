"""纯召回 JSON runtime 的 LINK-195 诊断字段测试。"""

import pytest

from src.application.recall_json_runtime import run_recall_json
from src.core.pipeline.recall import RecallDiagnostics, RecallHit, RecallRequest, RecallResponse


class _FakePipeline:
    async def execute(self, request: RecallRequest) -> RecallResponse:
        return RecallResponse(
            query=request.query,
            hits=[
                RecallHit(
                    chunk_id="c1",
                    doc_id=10,
                    dataset_id=1,
                    fused_score=0.1,
                    scores={"bm25": 3.0, "sparse": None, "dense": None},
                )
            ],
            per_source_counts={"bm25": 1, "sparse": 0, "dense": 0},
            failed_sources=[],
            elapsed_ms=1,
            recall_diagnostics=RecallDiagnostics(
                source_mode="bm25_only",
                degraded=True,
                active_sources=["bm25", "sparse", "dense"],
                per_source_counts={"bm25": 1, "sparse": 0, "dense": 0},
                empty_sources=["sparse", "dense"],
                failed_sources=[],
            ),
        )


@pytest.mark.asyncio
async def test_run_recall_json_returns_recall_diagnostics():
    payload = await run_recall_json(
        _FakePipeline(),
        RecallRequest(user_id=1, query="q", dataset_ids=[1]),
        request_id="rid",
    )

    assert payload["recall_diagnostics"] == {
        "source_mode": "bm25_only",
        "degraded": True,
        "active_sources": ["bm25", "sparse", "dense"],
        "per_source_counts": {"bm25": 1, "sparse": 0, "dense": 0},
        "empty_sources": ["sparse", "dense"],
        "failed_sources": [],
    }
    assert "reason" not in payload["recall_diagnostics"]
