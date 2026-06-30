from __future__ import annotations

import pytest

from src.core.encoding.sparse import factory


class _FakeSettings:
    """per-user 解析仍依赖的全局清洗 / 命名配置（与具体 provider 无关）。"""

    SPARSE_VECTOR_QDRANT_VECTOR_NAME = "sparse_text"
    SPARSE_VECTOR_TOP_K = 128
    SPARSE_VECTOR_MIN_WEIGHT = 0.02


def _patch_user_model_resolver(monkeypatch, *, resolved=None, raises=None):
    """替换 user_model_resolver.aresolve_user_model（解析函数内部 lazy import 它）。"""
    import src.core.llm.user_model_resolver as resolver_mod

    captured: dict[str, object] = {}

    async def fake_resolve(*, user_id, capability, **kwargs):
        captured["user_id"] = user_id
        captured["capability"] = capability
        if raises is not None:
            raise raises
        return resolved

    monkeypatch.setattr(resolver_mod, "aresolve_user_model", fake_resolve)
    return captured


def test_create_sparse_vector_service_wraps_encoder():
    """显式注入路径（测试 / 复用）：直接用编码器包出 service。"""

    class FakeEncoder:
        model_name = "fake-encoder"

        async def aencode(self, texts):
            return []

    service = factory.create_sparse_vector_service(FakeEncoder())

    assert service.model_name == "fake-encoder"


@pytest.mark.asyncio
async def test_aresolve_user_sparse_vector_service_builds_from_user_config(monkeypatch):
    from types import SimpleNamespace

    from src.core.encoding.sparse.adapter_encoder import AdapterSparseVectorEncoder

    class FakeProvider:
        provider_name = "bge_m3"

        def has_capability(self, capability):
            return True

    resolved = SimpleNamespace(provider=FakeProvider(), model_name="user-bge-m3")
    monkeypatch.setattr(factory, "settings", _FakeSettings())
    captured = _patch_user_model_resolver(monkeypatch, resolved=resolved)

    service = await factory.aresolve_user_sparse_vector_service(7)

    # 解析走的是用户的 SPARSE_EMBEDDING 配置。
    assert captured == {"user_id": 7, "capability": "SPARSE_EMBEDDING"}
    assert isinstance(service._encoder, AdapterSparseVectorEncoder)
    assert service.model_name == "user-bge-m3"
    assert service.vector_name == "sparse_text"
    # top_k / min_weight 取全局清洗配置，保证各 provider 召回侧表现一致。
    assert service._encoder._top_k == 128
    assert service._encoder._min_weight == 0.02


@pytest.mark.asyncio
async def test_aresolve_user_sparse_vector_service_raises_when_config_missing(monkeypatch):
    from src.core.llm.exceptions import UserModelConfigMissingError

    monkeypatch.setattr(factory, "settings", _FakeSettings())
    _patch_user_model_resolver(
        monkeypatch, raises=UserModelConfigMissingError("SPARSE_EMBEDDING", 7)
    )

    with pytest.raises(factory.SparseEmbeddingConfigMissingError):
        await factory.aresolve_user_sparse_vector_service(7)


@pytest.mark.asyncio
async def test_aresolve_dataset_sparse_vector_service_missing_binding_raises(monkeypatch):
    from src.core.dataset_config import VectorModelBindingConfig
    import src.core.dataset_config as dataset_config_pkg

    class _FakeDatasetConfigService:
        async def get_vector_model_binding(self, user_id, dataset_id, db):
            assert (user_id, dataset_id) == (7, 20)
            return VectorModelBindingConfig()

    monkeypatch.setattr(
        dataset_config_pkg,
        "DatasetConfigService",
        lambda: _FakeDatasetConfigService(),
    )

    with pytest.raises(factory.SparseEmbeddingConfigMissingError) as exc_info:
        await factory.aresolve_dataset_sparse_vector_service(
            user_id=7,
            dataset_id=20,
            db=object(),
        )

    message = str(exc_info.value)
    assert "Dataset 20" in message
    assert "sparse_embedding_config_id" in message
