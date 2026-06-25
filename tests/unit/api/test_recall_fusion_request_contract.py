"""RAG / recall HTTP 请求体不开放融合策略配置。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.api.routes import rag, recall
from src.application.recall_errors import RecallApiError


def _req_with_payload(payload: dict):
    async def _body():
        return json.dumps(payload).encode("utf-8")

    return SimpleNamespace(body=_body)


@pytest.mark.parametrize(
    "field",
    [
        "fusion_strategy",
        "fusion_weights",
        "recall_fusion_strategy",
        "fusion_bm25_weight",
        "fusion_sparse_weight",
        "fusion_dense_weight",
    ],
)
async def test_rag_stream_body_rejects_fusion_fields(field: str):
    payload = {
        "query": "q",
        "config_id": 1,
        "conversation_id": 2,
        "turn_id": "t-1",
        field: "weighted_score",
    }

    with pytest.raises(RecallApiError) as exc_info:
        await rag._parse_and_validate_body(_req_with_payload(payload))

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "RECALL_INVALID_REQUEST"


@pytest.mark.parametrize(
    "field",
    [
        "fusion_strategy",
        "fusion_weights",
        "recall_fusion_strategy",
        "fusion_bm25_weight",
        "fusion_sparse_weight",
        "fusion_dense_weight",
    ],
)
async def test_recall_json_body_rejects_fusion_fields(field: str):
    payload = {"query": "q", field: "weighted_score"}

    with pytest.raises(RecallApiError) as exc_info:
        await recall._parse_and_validate_body(_req_with_payload(payload))

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "RECALL_INVALID_REQUEST"


async def test_recall_json_maps_dataset_fusion_config_to_internal_request(monkeypatch):
    captured = {}

    async def _recall_config(user_id, dataset_ids):
        return SimpleNamespace(
            recall_result_limit=20,
            sparse_score_threshold=0.1,
            dense_score_threshold=0.2,
            recall_enabled_sources=["bm25", "sparse", "dense"],
            recall_strict=False,
            recall_fusion_strategy="weighted_score",
            fusion_bm25_weight=0.1,
            fusion_sparse_weight=0.2,
            fusion_dense_weight=0.7,
        )

    async def _run_recall_json(_pipeline, recall_req, _request_id):
        captured["request"] = recall_req
        return {"hits": [], "failed_sources": []}

    monkeypatch.setattr(recall, "resolve_dataset_scope", lambda _body_ids, _ctx: [7])
    monkeypatch.setattr(recall, "aresolve_recall_config", _recall_config)
    monkeypatch.setattr(recall, "run_recall_json", _run_recall_json)

    ctx = SimpleNamespace(user_id=42, request_id="rid")
    response = await recall.recall_json(
        _req_with_payload({"query": "q"}), ctx=ctx, pipeline=object()
    )

    assert response.status_code == 200
    recall_req = captured["request"]
    assert recall_req.fusion_strategy_override == "weighted_score"
    assert recall_req.fusion_bm25_weight_override == 0.1
    assert recall_req.fusion_sparse_weight_override == 0.2
    assert recall_req.fusion_dense_weight_override == 0.7
