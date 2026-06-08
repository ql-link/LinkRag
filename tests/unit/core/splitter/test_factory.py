from __future__ import annotations

import pytest

import src.core.splitter.factory as factory
from src.core.llm.interfaces import CapabilityType
from src.core.splitter import StructuredSemanticChunker
from src.core.splitter.element_derived_chunker import INLINE_TABLE_MAX_TOKENS


class _FakeEmbedder:
    def has_capability(self, capability):
        return capability == CapabilityType.EMBEDDING


def test_create_chunking_engine_should_pass_semantic_unit_from_settings(monkeypatch):
    monkeypatch.setattr(factory.settings, "CHUNKING_SEMANTIC_UNIT", "paragraph")
    monkeypatch.setattr(factory.settings, "CHUNKING_OVERLAP_TOKENS", 7)
    monkeypatch.setattr(factory.settings, "CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS", 192)
    monkeypatch.setattr(factory, "create_system_embedding_client", lambda: _FakeEmbedder())

    engine = factory.create_chunking_engine()

    assert isinstance(engine.chunker, StructuredSemanticChunker)
    assert engine.chunker.semantic_chunker.semantic_unit == "paragraph"
    assert engine.chunker.semantic_chunker.overlapper.effective_tokens == 7
    assert engine.chunker.semantic_chunker.overlapper.config.tokens == 7
    assert engine.chunker.candidate_chunker.min_candidate_chunk_tokens == 192
    assert INLINE_TABLE_MAX_TOKENS == 256


def test_create_chunking_engine_should_disable_overlap_when_tokens_is_zero(monkeypatch):
    monkeypatch.setattr(factory.settings, "CHUNKING_OVERLAP_TOKENS", 0)
    monkeypatch.setattr(factory, "create_system_embedding_client", lambda: _FakeEmbedder())

    engine = factory.create_chunking_engine()

    assert isinstance(engine.chunker, StructuredSemanticChunker)
    assert engine.chunker.semantic_chunker.overlapper.effective_tokens == 0


def test_create_chunking_engine_should_not_swallow_embedding_init_errors(monkeypatch):
    def _raise_missing_embedding():
        raise ValueError("missing embedding config")

    monkeypatch.setattr(factory, "create_system_embedding_client", _raise_missing_embedding)

    with pytest.raises(ValueError, match="missing embedding config"):
        factory.create_chunking_engine()


def test_create_chunk_embedding_pipeline_should_use_structured_chunker():
    pipeline = factory.create_chunk_embedding_pipeline()

    assert isinstance(pipeline.chunking_engine.chunker, StructuredSemanticChunker)
