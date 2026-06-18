from __future__ import annotations

import pytest

import src.core.splitter.factory as factory
from src.core.splitter import StructuredSemanticChunker
from src.core.splitter.element_derived_chunker import INLINE_TABLE_MAX_TOKENS
from src.core.splitter.stage_two_noop import NoopStageTwoAlgorithm
from src.core.splitter.stage_two_semantic_depth import SemanticDepthWindowStageTwo


class FakeEmbedder:
    async def embed(self, texts, model=None, **kwargs):
        del model, kwargs
        batch = [texts] if isinstance(texts, str) else list(texts)
        return type("EmbeddingResponse", (), {"embeddings": [[1.0, 0.0] for _ in batch]})()


def test_create_chunking_engine_should_pass_stage_algorithm_settings(monkeypatch):
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_ONE_ALGORITHM", "candidate_boundary")
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_TWO_ALGORITHM", "noop")
    monkeypatch.setattr(factory.settings, "CHUNKING_OVERLAP_TOKENS", 7)
    monkeypatch.setattr(factory.settings, "CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS", 192)
    monkeypatch.setattr(
        factory,
        "create_system_embedding_client",
        lambda: (_ for _ in ()).throw(AssertionError("should use lazy embedder")),
    )

    engine = factory.create_chunking_engine()

    assert isinstance(engine.chunker, StructuredSemanticChunker)
    assert engine.chunker.stage_one_router.algorithm_name == "candidate_boundary"
    assert engine.chunker.stage_two_router.algorithm_name == "noop"
    assert engine.chunker.stage_one_router.algorithm is engine.chunker.candidate_chunker
    assert engine.chunker.overlapper.effective_tokens == 7
    assert engine.chunker.overlapper.config.tokens == 7
    assert engine.chunker.candidate_chunker.min_candidate_chunk_tokens == 192
    assert isinstance(engine.chunker.stage_two_algorithm, NoopStageTwoAlgorithm)
    assert INLINE_TABLE_MAX_TOKENS == 256


def test_create_chunking_engine_should_route_noop_stage_two(monkeypatch):
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_ONE_ALGORITHM", "candidate_boundary")
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_TWO_ALGORITHM", "noop")
    monkeypatch.setattr(factory.settings, "CHUNKING_OVERLAP_TOKENS", 0)

    engine = factory.create_chunking_engine()

    assert isinstance(engine.chunker, StructuredSemanticChunker)
    assert engine.chunker.stage_two_router.algorithm_name == "noop"
    assert engine.chunker.stage_one_router.algorithm is engine.chunker.candidate_chunker
    assert engine.chunker.overlapper.effective_tokens == 0
    assert isinstance(engine.chunker.stage_two_algorithm, NoopStageTwoAlgorithm)


def test_create_chunking_engine_should_route_semantic_depth_with_lazy_embedder(monkeypatch):
    created = {"count": 0}

    def fail_if_materialized():
        created["count"] += 1
        raise AssertionError("lazy embedder should not materialize during factory wiring")

    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_ONE_ALGORITHM", "candidate_boundary")
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_TWO_ALGORITHM", "semantic_depth_window")
    monkeypatch.setattr(factory.settings, "CHUNKING_MAX_CHUNK_TOKENS", 512)
    monkeypatch.setattr(factory.settings, "CHUNKING_HARD_MAX_TOKENS", 1024)
    monkeypatch.setattr(factory.settings, "CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS", 128)
    monkeypatch.setattr(factory, "create_system_embedding_client", fail_if_materialized)

    engine = factory.create_chunking_engine()

    assert isinstance(engine.chunker.stage_two_algorithm, SemanticDepthWindowStageTwo)
    assert created["count"] == 0


def test_create_chunk_embedding_pipeline_reuses_embedder_for_stage_two(monkeypatch):
    fake_embedder = FakeEmbedder()
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_ONE_ALGORITHM", "candidate_boundary")
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_TWO_ALGORITHM", "semantic_depth_window")
    monkeypatch.setattr(factory.settings, "SYSTEM_LLM_PROVIDER", "qwen")
    monkeypatch.setattr(factory.settings, "SYSTEM_LLM_MODEL_EMBEDDING", "text-embedding-v4")
    monkeypatch.setattr(factory.settings, "CHUNK_INDEX_EMBED_BATCH_SIZE", 32)
    monkeypatch.setattr(factory, "create_lazy_system_embedding_client", lambda: fake_embedder)

    pipeline = factory.create_chunk_embedding_pipeline()

    stage_two = pipeline.chunking_engine.chunker.stage_two_algorithm
    assert pipeline.embedder is fake_embedder
    assert isinstance(stage_two, SemanticDepthWindowStageTwo)
    assert stage_two._scorer.embedder is fake_embedder


@pytest.mark.asyncio
async def test_user_chunk_embedding_pipeline_reuses_user_embedder(monkeypatch):
    fake_embedder = FakeEmbedder()

    async def resolve_user_embedding_client(user_id: int):
        assert user_id == 42
        return fake_embedder, "text-embedding-v4"

    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_ONE_ALGORITHM", "candidate_boundary")
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_TWO_ALGORITHM", "semantic_depth_window")
    monkeypatch.setattr(factory.settings, "CHUNK_INDEX_EMBED_BATCH_SIZE", 32)
    monkeypatch.setattr(factory, "aresolve_user_embedding_client", resolve_user_embedding_client)

    pipeline = await factory.aresolve_user_chunk_embedding_pipeline(42)

    stage_two = pipeline.chunking_engine.chunker.stage_two_algorithm
    assert pipeline.embedder is fake_embedder
    assert isinstance(stage_two, SemanticDepthWindowStageTwo)
    assert stage_two._scorer.embedder is fake_embedder
