from __future__ import annotations

import pytest

from src.core.encoding.sparse import factory
from src.core.encoding.sparse.exceptions import SparseVectorConfigurationError


def test_should_create_encoder_without_external_fp16_config(monkeypatch):
    captured_kwargs: dict[str, object] = {}

    class FakeSettings:
        SPARSE_VECTOR_PROVIDER = "bge_m3"
        SPARSE_VECTOR_MODEL_NAME = "BAAI/bge-m3"
        SPARSE_VECTOR_MODEL_CACHE_DIR = None
        SPARSE_VECTOR_LOCAL_FILES_ONLY = False
        SPARSE_VECTOR_DEVICE = "cpu"
        SPARSE_VECTOR_BATCH_SIZE = 12
        SPARSE_VECTOR_MAX_LENGTH = 8192
        SPARSE_VECTOR_QDRANT_VECTOR_NAME = "sparse_text"
        SPARSE_VECTOR_TOP_K = 256
        SPARSE_VECTOR_MIN_WEIGHT = 0.0

    class FakeEncoder:
        model_name = "BAAI/bge-m3"

        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        async def aencode(self, texts):
            return []

    monkeypatch.setattr(factory, "settings", FakeSettings())
    monkeypatch.setattr(factory, "BGEM3SparseVectorEncoder", FakeEncoder)

    service = factory.create_sparse_vector_service_from_settings()

    assert service.vector_name == "sparse_text"
    assert captured_kwargs["device"] == "cpu"
    assert "use_fp16" not in captured_kwargs


def test_should_build_http_encoder_when_provider_is_http(monkeypatch):
    captured_kwargs: dict[str, object] = {}

    class FakeSettings:
        SPARSE_VECTOR_PROVIDER = "bge_m3_http"
        SPARSE_VECTOR_MODEL_NAME = "BAAI/bge-m3"
        SPARSE_VECTOR_MAX_LENGTH = 8192
        SPARSE_VECTOR_QDRANT_VECTOR_NAME = "sparse_text"
        SPARSE_VECTOR_TOP_K = 256
        SPARSE_VECTOR_MIN_WEIGHT = 0.0
        SPARSE_VECTOR_HTTP_ENDPOINT = "http://103.205.254.30:37997"
        SPARSE_VECTOR_HTTP_TIMEOUT = 12.0
        SPARSE_VECTOR_HTTP_BATCH_SIZE = 8

    class FakeHttpEncoder:
        model_name = "BAAI/bge-m3"

        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        async def aencode(self, texts):
            return []

    monkeypatch.setattr(factory, "settings", FakeSettings())
    monkeypatch.setattr(factory, "BGEM3HttpSparseVectorEncoder", FakeHttpEncoder)

    service = factory.create_sparse_vector_service_from_settings()

    assert service.vector_name == "sparse_text"
    assert captured_kwargs["endpoint"] == "http://103.205.254.30:37997"
    assert captured_kwargs["timeout"] == 12.0
    assert captured_kwargs["batch_size"] == 8


def test_should_raise_for_unknown_provider(monkeypatch):
    class FakeSettings:
        SPARSE_VECTOR_PROVIDER = "unknown_provider"

    monkeypatch.setattr(factory, "settings", FakeSettings())

    with pytest.raises(SparseVectorConfigurationError):
        factory.create_sparse_vector_service_from_settings()


class _LlmAdapterSettings:
    SPARSE_VECTOR_PROVIDER = "llm_adapter"
    SPARSE_VECTOR_QDRANT_VECTOR_NAME = "sparse_text"
    SPARSE_VECTOR_TOP_K = 128
    SPARSE_VECTOR_MIN_WEIGHT = 0.02
    SPARSE_VECTOR_LLM_PROTOCOL = "vikingdb"
    SPARSE_VECTOR_LLM_API_KEY = "sk-test"
    SPARSE_VECTOR_LLM_API_BASE_URL = "https://example.com"
    SPARSE_VECTOR_LLM_MODEL_NAME = "bge-m3"


def _patch_model_factory(monkeypatch, *, has_sparse: bool):
    """把 _build_llm_adapter_encoder 内部 import 的 ModelFactory 换成可控替身。"""
    import src.core.llm.factory as llm_factory

    captured: dict[str, object] = {}

    class FakeProvider:
        provider_name = "vikingdb"

        def has_capability(self, capability):
            return has_sparse

    class FakeModelFactory:
        def create_client(self, **kwargs):
            captured.update(kwargs)
            return FakeProvider()

    monkeypatch.setattr(llm_factory, "ModelFactory", FakeModelFactory)
    return captured


def test_should_build_llm_adapter_encoder_when_provider_is_llm_adapter(monkeypatch):
    from src.core.encoding.sparse.adapter_encoder import AdapterSparseVectorEncoder

    monkeypatch.setattr(factory, "settings", _LlmAdapterSettings())
    captured = _patch_model_factory(monkeypatch, has_sparse=True)

    service = factory.create_sparse_vector_service_from_settings()

    assert service.vector_name == "sparse_text"
    assert isinstance(service._encoder, AdapterSparseVectorEncoder)
    assert service.model_name == "bge-m3"
    # protocol 必须按配置透传给 ModelFactory.create_client。
    assert captured["protocol"] == "vikingdb"
    assert captured["api_key"] == "sk-test"
    assert service._encoder._top_k == 128
    assert service._encoder._min_weight == 0.02


def test_should_raise_when_llm_adapter_protocol_missing(monkeypatch):
    class FakeSettings(_LlmAdapterSettings):
        SPARSE_VECTOR_LLM_PROTOCOL = None

    monkeypatch.setattr(factory, "settings", FakeSettings())
    _patch_model_factory(monkeypatch, has_sparse=True)

    with pytest.raises(SparseVectorConfigurationError):
        factory.create_sparse_vector_service_from_settings()


def test_should_raise_when_protocol_lacks_sparse_capability(monkeypatch):
    monkeypatch.setattr(factory, "settings", _LlmAdapterSettings())
    _patch_model_factory(monkeypatch, has_sparse=False)

    with pytest.raises(SparseVectorConfigurationError):
        factory.create_sparse_vector_service_from_settings()


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


@pytest.mark.asyncio
async def test_aresolve_user_sparse_vector_service_builds_from_user_config(monkeypatch):
    from types import SimpleNamespace

    from src.core.encoding.sparse.adapter_encoder import AdapterSparseVectorEncoder

    class FakeProvider:
        provider_name = "bge_m3"

        def has_capability(self, capability):
            return True

    resolved = SimpleNamespace(provider=FakeProvider(), model_name="user-bge-m3")
    monkeypatch.setattr(factory, "settings", _LlmAdapterSettings())
    captured = _patch_user_model_resolver(monkeypatch, resolved=resolved)

    service = await factory.aresolve_user_sparse_vector_service(7)

    # 解析走的是用户的 SPARSE_EMBEDDING 配置。
    assert captured == {"user_id": 7, "capability": "SPARSE_EMBEDDING"}
    assert isinstance(service._encoder, AdapterSparseVectorEncoder)
    assert service.model_name == "user-bge-m3"
    assert service.vector_name == "sparse_text"
    # top_k / min_weight 仍取全局清洗配置，与系统级路径一致。
    assert service._encoder._top_k == 128
    assert service._encoder._min_weight == 0.02


@pytest.mark.asyncio
async def test_aresolve_user_sparse_vector_service_raises_when_config_missing(monkeypatch):
    from src.core.llm.exceptions import UserModelConfigMissingError

    monkeypatch.setattr(factory, "settings", _LlmAdapterSettings())
    _patch_user_model_resolver(
        monkeypatch, raises=UserModelConfigMissingError("SPARSE_EMBEDDING", 7)
    )

    with pytest.raises(factory.SparseEmbeddingConfigMissingError):
        await factory.aresolve_user_sparse_vector_service(7)


def test_should_build_remote_encoder_when_provider_is_remote_bge_m3(monkeypatch):
    captured_kwargs: dict[str, object] = {}

    class FakeSettings:
        SPARSE_VECTOR_PROVIDER = "remote_bge_m3"
        SPARSE_VECTOR_QDRANT_VECTOR_NAME = "sparse_text"
        SPARSE_VECTOR_TOP_K = 200
        SPARSE_VECTOR_MIN_WEIGHT = 0.05
        BGE_M3_SERVICE_URL = "http://127.0.0.1:7997"
        BGE_M3_TIMEOUT_SECONDS = 15.0
        BGE_M3_MAX_RETRIES = 5

    class FakeRemoteEncoder:
        model_name = "http://127.0.0.1:7997"

        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        async def aencode(self, texts):
            return []

    monkeypatch.setattr(factory, "settings", FakeSettings())
    monkeypatch.setattr(factory, "RemoteBGEM3Encoder", FakeRemoteEncoder)

    service = factory.create_sparse_vector_service_from_settings()

    assert service.vector_name == "sparse_text"
    assert captured_kwargs["service_url"] == "http://127.0.0.1:7997"
    assert captured_kwargs["timeout_seconds"] == 15.0
    assert captured_kwargs["max_retries"] == 5
    assert captured_kwargs["top_k"] == 200
    assert captured_kwargs["min_weight"] == 0.05
