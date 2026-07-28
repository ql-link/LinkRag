"""RecallConfig → RecallRequest 映射测试（LINK-136）。

入口层统一走 ``build_recall_request_from_config``，确保 RAG 流和纯召回 JSON 不会在新增
配置字段时失同步。
"""

from __future__ import annotations

from src.application import recall_pipeline_provider as provider
from src.application.recall_pipeline_provider import build_recall_request_from_config
from src.core.dataset_config import RecallConfig


def test_build_recall_request_maps_fusion_limit_and_route_top_k():
    recall_cfg = RecallConfig(
        recall_result_limit=64,
        recall_context_token_budget=4000,
        bm25_top_k=101,
        sparse_top_k=51,
        sparse_score_threshold=0.2,
        dense_top_k=99,
        dense_score_threshold=0.7,
        recall_enabled_sources=["bm25", "dense"],
        recall_fusion_strategy="weighted_score",
        rrf_k=10,
        fusion_bm25_weight=0.1,
        fusion_sparse_weight=0.2,
        fusion_dense_weight=0.7,
        rerank_top_n=6,
        recall_strict=True,
    )

    request = build_recall_request_from_config(
        query="合同付款",
        user_id=7,
        dataset_ids=[10],
        doc_ids=[100, 101],
        recall_cfg=recall_cfg,
    )

    assert request.query == "合同付款"
    assert request.user_id == 7
    assert request.dataset_ids == [10]
    assert request.doc_ids == [100, 101]
    assert request.top_k == 64
    assert request.bm25_top_k == 101
    assert request.sparse_top_k == 51
    assert request.dense_top_k == 99
    assert request.sparse_score_threshold_override == 0.2
    assert request.dense_score_threshold_override == 0.7
    assert request.enabled_sources == ["bm25", "dense"]
    assert request.strict_override is True
    assert request.fusion_strategy_override == "weighted_score"
    assert request.rrf_k_override == 10
    assert request.fusion_bm25_weight_override == 0.1
    assert request.fusion_sparse_weight_override == 0.2
    assert request.fusion_dense_weight_override == 0.7


def test_ltr_rollout_forces_frozen_system_weighted_fusion(monkeypatch):
    monkeypatch.setattr(provider.settings, "RECALL_LTR_MODE", "shadow")
    monkeypatch.setattr(provider.settings, "RECALL_FUSION_BM25_WEIGHT", 0.15)
    monkeypatch.setattr(provider.settings, "RECALL_FUSION_SPARSE_WEIGHT", 0.15)
    monkeypatch.setattr(provider.settings, "RECALL_FUSION_DENSE_WEIGHT", 0.70)
    recall_cfg = RecallConfig(
        recall_fusion_strategy="rrf",
        fusion_bm25_weight=0.2,
        fusion_sparse_weight=0.3,
        fusion_dense_weight=0.5,
    )

    request = build_recall_request_from_config(
        query="合同付款",
        user_id=7,
        dataset_ids=[10],
        recall_cfg=recall_cfg,
    )

    assert request.fusion_strategy_override == "weighted_score"
    assert request.fusion_bm25_weight_override == 0.15
    assert request.fusion_sparse_weight_override == 0.15
    assert request.fusion_dense_weight_override == 0.70
