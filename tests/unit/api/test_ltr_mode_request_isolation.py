from src.api.routes.rag import _build_mode_recall_requests
from src.application.recall_pipeline_provider import build_recall_request_from_config
from src.config import settings
from src.core.dataset_config import RecallConfig


def test_shadow_serving_request_matches_off_and_keeps_dataset_top_n(monkeypatch):
    recall_cfg = RecallConfig(
        bm25_top_k=11,
        sparse_top_k=12,
        dense_top_k=13,
        recall_enabled_sources=["bm25", "dense"],
        rerank_top_n=7,
        fusion_bm25_weight=0.4,
        fusion_sparse_weight=0.0,
        fusion_dense_weight=0.6,
    )

    monkeypatch.setattr(settings, "RECALL_LTR_MODE", "off")
    off_request, off_shadow, off_top_n = _build_mode_recall_requests(
        query="合同付款",
        user_id=1,
        dataset_ids=[10],
        recall_cfg=recall_cfg,
        dataset_contexts={},
    )
    monkeypatch.setattr(settings, "RECALL_LTR_MODE", "shadow")
    shadow_serving, shadow_background, shadow_top_n = _build_mode_recall_requests(
        query="合同付款",
        user_id=1,
        dataset_ids=[10],
        recall_cfg=recall_cfg,
        dataset_contexts={},
    )

    assert shadow_serving == off_request
    assert shadow_top_n == off_top_n == 7
    assert off_shadow is None
    assert shadow_background is not None
    assert shadow_background.candidate_contract_version is not None
    assert shadow_background.required_sources == ["bm25", "sparse", "dense"]


def test_active_and_baseline_use_frozen_contract_and_top_n(monkeypatch):
    recall_cfg = RecallConfig(rerank_top_n=7)

    for mode in ("active", "baseline"):
        monkeypatch.setattr(settings, "RECALL_LTR_MODE", mode)
        request, shadow_request, top_n = _build_mode_recall_requests(
            query="合同付款",
            user_id=1,
            dataset_ids=[10],
            recall_cfg=recall_cfg,
            dataset_contexts={},
        )
        assert request.candidate_contract_version is not None
        assert request.required_sources == ["bm25", "sparse", "dense"]
        assert shadow_request is None
        assert top_n == 10


def test_pure_recall_request_is_invariant_across_ltr_mode_switches(monkeypatch):
    """ISO-001/002/003/004/006: pure recall never inherits global LTR rollout semantics."""

    recall_cfg = RecallConfig(
        bm25_top_k=31,
        sparse_top_k=17,
        dense_top_k=43,
        recall_enabled_sources=["bm25", "dense"],
        recall_result_limit=9,
        fusion_bm25_weight=0.35,
        fusion_sparse_weight=0.0,
        fusion_dense_weight=0.65,
    )
    requests = []
    for mode in ("off", "shadow", "active", "baseline", "off"):
        monkeypatch.setattr(settings, "RECALL_LTR_MODE", mode)
        requests.append(
            build_recall_request_from_config(
                query="合同编号 A-2026-01",
                user_id=1,
                dataset_ids=[10],
                recall_cfg=recall_cfg,
                dataset_contexts={},
            )
        )

    assert all(request == requests[0] for request in requests[1:])
    request = requests[0]
    assert request.enabled_sources == ["bm25", "dense"]
    assert (request.bm25_top_k, request.sparse_top_k, request.dense_top_k) == (31, 17, 43)
    assert request.top_k == 9
    assert (
        request.fusion_bm25_weight_override,
        request.fusion_sparse_weight_override,
        request.fusion_dense_weight_override,
    ) == (0.35, 0.0, 0.65)
    assert request.candidate_contract_version is None
    assert request.required_sources is None
