"""RecallConfig → RecallRequest 映射测试（LINK-136）。

入口层统一走 ``build_recall_request_from_config``，确保 RAG 流和纯召回 JSON 不会在新增
配置字段时失同步。
"""

from __future__ import annotations

from src.application import recall_pipeline_provider as provider
from src.application.recall_pipeline_provider import build_recall_request_from_config
from src.core.dataset_config import RecallConfig


def test_build_recall_request_maps_fusion_limit_and_route_top_k(monkeypatch):
    monkeypatch.setattr(provider.settings, "RECALL_LTR_MODE", "off")
    recall_cfg = RecallConfig(
        recall_result_limit=64,
        recall_context_token_budget=4000,
        bm25_top_k=101,
        sparse_top_k=51,
        sparse_score_threshold=0.2,
        dense_top_k=99,
        dense_score_threshold=0.7,
        recall_enabled_sources=["bm25", "dense"],
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
    assert request.fusion_bm25_weight_override == 0.1
    assert request.fusion_sparse_weight_override == 0.2
    assert request.fusion_dense_weight_override == 0.7


def test_ltr_rollout_applies_frozen_candidate_serving_contract(monkeypatch):
    monkeypatch.setattr(provider.settings, "RECALL_LTR_MODE", "shadow")
    monkeypatch.setattr(provider.settings, "RECALL_FUSION_BM25_WEIGHT", 0.15)
    monkeypatch.setattr(provider.settings, "RECALL_FUSION_SPARSE_WEIGHT", 0.15)
    monkeypatch.setattr(provider.settings, "RECALL_FUSION_DENSE_WEIGHT", 0.70)
    recall_cfg = RecallConfig(
        fusion_bm25_weight=0.2,
        fusion_sparse_weight=0.3,
        fusion_dense_weight=0.5,
    )

    request = build_recall_request_from_config(
        query="合同付款",
        user_id=7,
        dataset_ids=[10],
        recall_cfg=recall_cfg,
        apply_ltr_serving_contract=True,
    )

    assert request.fusion_bm25_weight_override == 0.15
    assert request.fusion_sparse_weight_override == 0.15
    assert request.fusion_dense_weight_override == 0.70
    assert request.enabled_sources == ["bm25", "sparse", "dense"]
    assert request.dense_top_k == 300
    assert request.sparse_top_k == 100
    assert request.bm25_top_k == 225
    assert request.dense_score_threshold_override == 0.0
    assert request.sparse_score_threshold_override == 0.0
    assert request.candidate_contract_version == "blind_v5_candidate_routing_v1"
    assert request.candidate_profile == "short_keyword"


def test_pure_recall_keeps_dataset_candidate_config_during_ltr_rollout(monkeypatch):
    monkeypatch.setattr(provider.settings, "RECALL_LTR_MODE", "active")
    recall_cfg = RecallConfig(
        bm25_top_k=17,
        sparse_top_k=18,
        dense_top_k=19,
        sparse_score_threshold=0.4,
        dense_score_threshold=0.5,
        recall_enabled_sources=["dense"],
        fusion_bm25_weight=0.1,
        fusion_sparse_weight=0.2,
        fusion_dense_weight=0.7,
    )

    request = build_recall_request_from_config(
        query="合同付款",
        user_id=7,
        dataset_ids=[10],
        recall_cfg=recall_cfg,
    )

    assert (request.bm25_top_k, request.sparse_top_k, request.dense_top_k) == (17, 18, 19)
    assert request.enabled_sources == ["dense"]
    assert request.sparse_score_threshold_override == 0.4
    assert request.dense_score_threshold_override == 0.5
    assert request.fusion_bm25_weight_override == 0.1
    assert request.candidate_contract_version is None


def test_shadow_serving_request_keeps_dataset_contract(monkeypatch):
    """Shadow 主请求不因全局模式而套用冻结候选契约。"""
    monkeypatch.setattr(provider.settings, "RECALL_LTR_MODE", "shadow")
    recall_cfg = RecallConfig(
        bm25_top_k=17,
        sparse_top_k=18,
        dense_top_k=19,
        recall_enabled_sources=["bm25", "dense"],
        fusion_bm25_weight=0.4,
        fusion_sparse_weight=0.0,
        fusion_dense_weight=0.6,
    )

    request = build_recall_request_from_config(
        query="合同付款",
        user_id=7,
        dataset_ids=[10],
        recall_cfg=recall_cfg,
        apply_ltr_serving_contract=False,
    )

    assert (request.bm25_top_k, request.sparse_top_k, request.dense_top_k) == (17, 18, 19)
    assert request.enabled_sources == ["bm25", "dense"]
    assert request.fusion_bm25_weight_override == 0.4
    assert request.candidate_contract_version is None
    assert request.required_sources is None
