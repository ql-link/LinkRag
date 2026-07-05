"""RecallPipeline provider 装配配置测试。"""

from __future__ import annotations

from src.application import recall_pipeline_provider as provider
from src.core.pipeline.recall import SOURCE_BM25
from tests.unit.core.pipeline.recall.conftest import FakeRetriever


def test_build_pipeline_injects_recall_fusion_settings(monkeypatch):
    monkeypatch.setattr(provider.settings, "RECALL_ENABLED_SOURCES", SOURCE_BM25)
    monkeypatch.setattr(provider.settings, "RECALL_STRICT_DEFAULT", True)
    monkeypatch.setattr(provider.settings, "RECALL_FUSION_STRATEGY", "weighted_score")
    monkeypatch.setattr(provider.settings, "RECALL_RRF_K", 10)
    monkeypatch.setattr(provider.settings, "RECALL_FUSION_BM25_WEIGHT", 0.2)
    monkeypatch.setattr(provider.settings, "RECALL_FUSION_SPARSE_WEIGHT", 0.3)
    monkeypatch.setattr(provider.settings, "RECALL_FUSION_DENSE_WEIGHT", 0.5)
    monkeypatch.setattr(
        provider,
        "_BUILDERS",
        {SOURCE_BM25: lambda: FakeRetriever(source=SOURCE_BM25, hits=[])},
    )

    pipeline = provider._build_pipeline()

    assert pipeline._config.strict is True
    assert pipeline._config.rrf_k == 10
    assert pipeline._config.fusion_strategy == "weighted_score"
    assert pipeline._config.fusion_bm25_weight == 0.2
    assert pipeline._config.fusion_sparse_weight == 0.3
    assert pipeline._config.fusion_dense_weight == 0.5
