from __future__ import annotations

from types import SimpleNamespace

from src.core.encoding.sparse import factory
from src.core.encoding.sparse.adapter_encoder import AdapterSparseVectorEncoder


class _FakeSettings:
    SPARSE_VECTOR_QDRANT_VECTOR_NAME = "dataset_sparse"
    SPARSE_VECTOR_TOP_K = 128
    SPARSE_VECTOR_MIN_WEIGHT = 0.02


def test_create_sparse_vector_service_wraps_encoder():
    class FakeEncoder:
        model_name = "fake-encoder"

        async def aencode(self, texts):
            return []

    service = factory.create_sparse_vector_service(FakeEncoder())

    assert service.model_name == "fake-encoder"


def test_build_sparse_vector_service_uses_exact_resolved_snapshot(monkeypatch):
    provider = SimpleNamespace(provider_name="bge_m3")
    resolved = SimpleNamespace(
        provider=provider,
        model_name="dataset-bge-m3",
        provider_type="qwen",
        config_id=812,
    )
    monkeypatch.setattr(factory, "settings", _FakeSettings())

    service = factory.build_sparse_vector_service(resolved)

    assert isinstance(service._encoder, AdapterSparseVectorEncoder)
    assert service._encoder._provider is provider
    assert service.model_name == "dataset-bge-m3"
    assert service.provider_type == "qwen"
    assert service.config_id == 812
    assert service.vector_name == "dataset_sparse"
    assert service._encoder._top_k == 128
    assert service._encoder._min_weight == 0.02
