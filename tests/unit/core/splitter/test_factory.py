from __future__ import annotations

import pytest

import src.core.splitter.factory as factory
from src.core.dataset_config import ChunkingConfig
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


def test_create_chunking_engine_semantic_depth_requires_exact_embedder(monkeypatch):
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_ONE_ALGORITHM", "candidate_boundary")
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_TWO_ALGORITHM", "semantic_depth_window")
    monkeypatch.setattr(factory.settings, "CHUNKING_MAX_CHUNK_TOKENS", 512)
    monkeypatch.setattr(factory.settings, "CHUNKING_HARD_MAX_TOKENS", 1024)
    monkeypatch.setattr(factory.settings, "CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS", 128)
    with pytest.raises(ValueError, match="dataset dense embedding resolved model"):
        factory.create_chunking_engine()


def test_create_chunking_engine_should_prefer_dataset_chunking_config(monkeypatch):
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_ONE_ALGORITHM", "candidate_boundary")
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_TWO_ALGORITHM", "noop")
    monkeypatch.setattr(factory.settings, "CHUNKING_OVERLAP_TOKENS", 0)
    monkeypatch.setattr(factory.settings, "CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS", 128)
    monkeypatch.setattr(factory.settings, "CHUNKING_MAX_CHUNK_TOKENS", 512)
    monkeypatch.setattr(factory.settings, "CHUNKING_HARD_MAX_TOKENS", 1024)
    monkeypatch.setattr(factory.settings, "CHUNKING_HEADING_BREAK_LEVEL", 3)
    monkeypatch.setattr(factory.settings, "CHUNKING_PROTECTED_NEIGHBOR_OVERLAP", False)

    config = ChunkingConfig(
        heading_break_level=5,
        min_candidate_chunk_tokens=192,
        overlap_tokens=32,
        max_chunk_tokens=768,
        hard_max_tokens=1536,
        stage_two_algorithm="semantic_depth_window",
        protected_neighbor_overlap=True,
    )

    engine = factory.create_chunking_engine(config=config, embedder=FakeEmbedder())
    chunker = engine.chunker
    stage_two = chunker.stage_two_algorithm

    assert chunker.stage_two_router.algorithm_name == "semantic_depth_window"
    assert isinstance(stage_two, SemanticDepthWindowStageTwo)
    assert stage_two.max_chunk_tokens == 768
    assert chunker.candidate_chunker.min_candidate_chunk_tokens == 192
    assert chunker.candidate_chunker.heading_break_level == 5
    assert chunker.overlapper.effective_tokens == 32
    assert chunker._protected_neighbor_overlap is True
    assert chunker.final_validator.hard_max_tokens == 1536


def test_create_chunking_engine_dataset_stage_two_config_affects_runtime_output(monkeypatch):
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_ONE_ALGORITHM", "candidate_boundary")
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_TWO_ALGORITHM", "noop")

    config = ChunkingConfig(
        min_candidate_chunk_tokens=128,
        overlap_tokens=0,
        max_chunk_tokens=256,
        hard_max_tokens=512,
        stage_two_algorithm="semantic_depth_window",
    )
    markdown = "# Runtime data area\n\n" + " ".join(f"word{i}" for i in range(320))

    engine = factory.create_chunking_engine(config=config, embedder=FakeEmbedder())
    chunks = engine.process(markdown, source_file="runtime.md")

    assert engine.chunker.stage_two_router.algorithm_name == "semantic_depth_window"
    assert chunks
    assert {chunk.metadata["split_strategy"] for chunk in chunks} == {
        "candidate_boundary + semantic_depth_window"
    }


def test_create_chunking_engine_dataset_noop_should_override_global_semantic(monkeypatch):
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_ONE_ALGORITHM", "candidate_boundary")
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_TWO_ALGORITHM", "semantic_depth_window")
    monkeypatch.setattr(factory.settings, "CHUNKING_PROTECTED_NEIGHBOR_OVERLAP", True)

    config = ChunkingConfig(
        stage_two_algorithm="noop",
        protected_neighbor_overlap=False,
    )

    engine = factory.create_chunking_engine(config=config, embedder=FakeEmbedder())

    assert engine.chunker.stage_two_router.algorithm_name == "noop"
    assert isinstance(engine.chunker.stage_two_algorithm, NoopStageTwoAlgorithm)
    assert engine.chunker._protected_neighbor_overlap is False


def test_build_chunk_embedding_pipeline_reuses_exact_embedder_for_stage_two(monkeypatch):
    from types import SimpleNamespace

    fake_embedder = FakeEmbedder()
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_ONE_ALGORITHM", "candidate_boundary")
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_TWO_ALGORITHM", "semantic_depth_window")
    monkeypatch.setattr(factory.settings, "CHUNK_INDEX_EMBED_BATCH_SIZE", 32)
    resolved = SimpleNamespace(
        provider=fake_embedder,
        model_name="text-embedding-v4",
        provider_type="qwen",
        config_id=42,
    )

    pipeline = factory.build_chunk_embedding_pipeline(resolved)

    stage_two = pipeline.chunking_engine.chunker.stage_two_algorithm
    assert pipeline.embedder._embedder is fake_embedder
    assert pipeline.embedder.config_id == 42
    assert isinstance(stage_two, SemanticDepthWindowStageTwo)
    assert stage_two._scorer.embedder is pipeline.embedder


def test_build_chunk_embedding_pipeline_preserves_global_config_id(monkeypatch):
    from types import SimpleNamespace

    fake_embedder = FakeEmbedder()

    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_ONE_ALGORITHM", "candidate_boundary")
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_TWO_ALGORITHM", "semantic_depth_window")
    monkeypatch.setattr(factory.settings, "CHUNK_INDEX_EMBED_BATCH_SIZE", 32)
    resolved = SimpleNamespace(
        provider=fake_embedder,
        model_name="text-embedding-v4",
        provider_type="qwen",
        config_id=9001,
    )

    pipeline = factory.build_chunk_embedding_pipeline(resolved)

    stage_two = pipeline.chunking_engine.chunker.stage_two_algorithm
    assert pipeline.embedder._embedder is fake_embedder
    assert pipeline.embedder.config_id == 9001
    assert isinstance(stage_two, SemanticDepthWindowStageTwo)
    assert stage_two._scorer.embedder is pipeline.embedder
