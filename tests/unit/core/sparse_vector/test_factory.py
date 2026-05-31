from __future__ import annotations

import pytest

from src.core.sparse_vector import factory
from src.core.sparse_vector.exceptions import SparseVectorConfigurationError


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
