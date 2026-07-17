"""Splitter 只消费 DatasetExecutionContext 已解析的 EMBEDDING 快照。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.core.splitter.factory as factory
from src.core.llm.interfaces import CapabilityType
from src.core.splitter.models import Chunk


class _Embedder:
    def __init__(self, *, provider_type="qwen", api_base_url=None):
        self.provider_type = provider_type
        self.api_base_url = api_base_url
        self.models = []
        self.batch_sizes = []

    def has_capability(self, capability):
        return capability is CapabilityType.EMBEDDING

    async def embed(self, texts, model=None, **_kwargs):
        self.models.append(model)
        self.batch_sizes.append(len(texts))
        return SimpleNamespace(
            embeddings=[[0.1, 0.2] for _ in texts],
            usage=None,
        )


def _resolved(provider, *, model="text-embedding-v4", config_id=42):
    return SimpleNamespace(
        provider=provider,
        provider_type=provider.provider_type,
        model_name=model,
        config_id=config_id,
    )


@pytest.mark.asyncio
async def test_model_bound_embedder_forces_snapshot_model_and_keeps_config_id():
    provider = _Embedder()
    embedder = factory.build_embedding_client(_resolved(provider))

    await embedder.embed(["hello"], model=None)

    assert provider.models == ["text-embedding-v4"]
    assert embedder.config_id == 42


def test_semantic_depth_requires_explicit_resolved_embedder(monkeypatch):
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_TWO_ALGORITHM", "semantic_depth_window")
    with pytest.raises(ValueError, match="requires the dataset dense embedding"):
        factory.create_chunking_engine(embedder=None)


@pytest.mark.asyncio
async def test_pipeline_uses_exact_snapshot_and_provider_batch_cap(monkeypatch):
    provider = _Embedder(
        provider_type="linkrag",
        api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
    )
    monkeypatch.setattr(factory.settings, "CHUNK_INDEX_EMBED_BATCH_SIZE", 32)
    pipeline = factory.build_chunk_embedding_pipeline(
        _resolved(provider, model="text-embedding-v3", config_id=15)
    )
    chunks = [Chunk(content=f"chunk-{index}", start_line=index, end_line=index) for index in range(22)]

    results = await pipeline.aembed_chunks(chunks)

    assert pipeline.embedding_model == "text-embedding-v3"
    assert pipeline.batch_size == 10
    assert provider.models == ["text-embedding-v3"] * 3
    assert provider.batch_sizes == [10, 10, 2]
    assert len(results) == 22


def test_non_dashscope_linkrag_endpoint_keeps_configured_batch_size():
    assert factory._resolve_embed_batch_size(
        provider_type="linkrag",
        model_name="text-embedding-v3",
        configured_batch_size=32,
        api_base_url="https://embedding.example.com/v1/embeddings",
    ) == 32
