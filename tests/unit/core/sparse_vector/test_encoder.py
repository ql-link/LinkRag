from __future__ import annotations

import inspect
import sys
from types import SimpleNamespace

import pytest

from src.core.sparse_vector import BGEM3SparseVectorEncoder, SparseVectorEncodingError, SparseVectorOutputError
from src.core.sparse_vector import encoder as encoder_module
from src.core.sparse_vector.exceptions import SparseVectorConfigurationError


class FakeBGEM3Model:
    def __init__(self, lexical_weights):
        self.lexical_weights = lexical_weights
        self.calls = []

    def encode(self, texts, **kwargs):
        self.calls.append((texts, kwargs))
        return {"lexical_weights": self.lexical_weights}


def test_should_not_accept_external_fp16_parameter():
    signature = inspect.signature(BGEM3SparseVectorEncoder)

    assert "use_fp16" not in signature.parameters


def test_should_load_bge_m3_with_fp32_on_cpu(monkeypatch):
    captured_kwargs: dict[str, object] = {}

    class FakeBGEM3FlagModel:
        def __init__(self, model_name, **kwargs):
            captured_kwargs["model_name"] = model_name
            captured_kwargs.update(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "FlagEmbedding",
        SimpleNamespace(BGEM3FlagModel=FakeBGEM3FlagModel),
    )
    monkeypatch.setattr(encoder_module, "resolve_sparse_vector_device", lambda device: "cpu")

    encoder = BGEM3SparseVectorEncoder(model_name="BAAI/bge-m3", device="cpu")

    encoder._get_model()

    assert captured_kwargs["model_name"] == "BAAI/bge-m3"
    assert captured_kwargs["devices"] == "cpu"
    assert captured_kwargs["use_fp16"] is False


def test_should_load_bge_m3_with_fp16_on_cuda(monkeypatch):
    captured_kwargs: dict[str, object] = {}

    class FakeBGEM3FlagModel:
        def __init__(self, model_name, **kwargs):
            captured_kwargs["model_name"] = model_name
            captured_kwargs.update(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "FlagEmbedding",
        SimpleNamespace(BGEM3FlagModel=FakeBGEM3FlagModel),
    )
    monkeypatch.setattr(encoder_module, "resolve_sparse_vector_device", lambda device: "cuda:0")

    encoder = BGEM3SparseVectorEncoder(model_name="BAAI/bge-m3", device="cuda:0")

    encoder._get_model()

    assert captured_kwargs["model_name"] == "BAAI/bge-m3"
    assert captured_kwargs["devices"] == "cuda:0"
    assert captured_kwargs["use_fp16"] is True


def test_should_reject_explicit_cuda_when_unavailable(monkeypatch):
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    with pytest.raises(SparseVectorConfigurationError, match="CUDA is unavailable"):
        encoder_module.resolve_sparse_vector_device("cuda")


@pytest.mark.asyncio
async def test_should_normalize_lexical_weights_from_fake_bge_m3_model():
    model = FakeBGEM3Model([
        {"7": 0.2, "3": 0.4},
        {11: 1.5, "2": 0.1},
    ])
    encoder = BGEM3SparseVectorEncoder(model=model, top_k=0)

    vectors = await encoder.aencode(["alpha", "beta"])

    assert vectors[0].indices == [3, 7]
    assert vectors[0].values == [0.4, 0.2]
    assert vectors[1].indices == [2, 11]
    assert vectors[1].values == [0.1, 1.5]
    assert model.calls[0][1]["return_sparse"] is True
    assert model.calls[0][1]["return_dense"] is False


@pytest.mark.asyncio
async def test_should_apply_top_k_by_weight_then_return_indices_sorted():
    model = FakeBGEM3Model([{1: 0.1, 2: 0.9, 3: 0.8, 4: 0.7}])
    encoder = BGEM3SparseVectorEncoder(model=model, top_k=2)

    vectors = await encoder.aencode(["alpha"])

    assert vectors[0].indices == [2, 3]
    assert vectors[0].values == [0.9, 0.8]


@pytest.mark.asyncio
async def test_should_filter_min_weight_and_empty_output_fails():
    model = FakeBGEM3Model([{1: 0.05, 2: 0.1}])
    encoder = BGEM3SparseVectorEncoder(model=model, min_weight=0.2)

    with pytest.raises(SparseVectorOutputError):
        await encoder.aencode(["alpha"])


@pytest.mark.asyncio
async def test_should_fail_when_output_count_mismatches_input_count():
    model = FakeBGEM3Model([{1: 0.5}])
    encoder = BGEM3SparseVectorEncoder(model=model)

    with pytest.raises(SparseVectorEncodingError, match="count"):
        await encoder.aencode(["alpha", "beta"])


@pytest.mark.asyncio
async def test_should_fail_when_lexical_weight_item_is_invalid():
    model = FakeBGEM3Model([{object(): "bad"}])
    encoder = BGEM3SparseVectorEncoder(model=model)

    with pytest.raises(SparseVectorEncodingError):
        await encoder.aencode(["alpha"])
