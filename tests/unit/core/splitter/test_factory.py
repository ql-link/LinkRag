from __future__ import annotations

import src.core.splitter.factory as factory
from src.core.splitter import StructuredSemanticChunker
from src.core.splitter.element_derived_chunker import INLINE_TABLE_MAX_TOKENS
from src.core.splitter.stage_two_noop import NoopStageTwoAlgorithm


def test_create_chunking_engine_should_pass_stage_algorithm_settings(monkeypatch):
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_ONE_ALGORITHM", "candidate_boundary")
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_TWO_ALGORITHM", "semantic_oversized")
    monkeypatch.setattr(factory.settings, "CHUNKING_SEMANTIC_UNIT", "paragraph")
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
    assert engine.chunker.stage_two_router.algorithm_name == "semantic_oversized"
    assert engine.chunker.semantic_chunker.semantic_unit == "paragraph"
    assert engine.chunker.semantic_chunker.overlapper.effective_tokens == 7
    assert engine.chunker.semantic_chunker.overlapper.config.tokens == 7
    assert engine.chunker.candidate_chunker.min_candidate_chunk_tokens == 192
    assert INLINE_TABLE_MAX_TOKENS == 256


def test_create_chunking_engine_should_route_noop_without_semantic_chunker(monkeypatch):
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_ONE_ALGORITHM", "candidate_boundary")
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_TWO_ALGORITHM", "noop")
    monkeypatch.setattr(factory.settings, "CHUNKING_OVERLAP_TOKENS", 0)

    engine = factory.create_chunking_engine()

    assert isinstance(engine.chunker, StructuredSemanticChunker)
    assert engine.chunker.stage_two_router.algorithm_name == "noop"
    assert engine.chunker.semantic_chunker is None
    assert engine.chunker.overlapper.effective_tokens == 0
    assert isinstance(engine.chunker.oversized_refiner, NoopStageTwoAlgorithm)
