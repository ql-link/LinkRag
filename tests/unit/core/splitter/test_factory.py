from __future__ import annotations

import src.core.splitter.factory as factory
from src.core.llm.interfaces import CapabilityType
from src.core.splitter import StructuredSemanticChunker


class _FakeEmbedder:
    def has_capability(self, capability):
        return capability == CapabilityType.EMBEDDING


def test_create_chunking_engine_should_pass_semantic_unit_from_settings(monkeypatch):
    monkeypatch.setattr(factory.settings, "CHUNKING_ENABLE_ADVANCED_PIPELINE", True)
    monkeypatch.setattr(factory.settings, "CHUNKING_SEMANTIC_UNIT", "paragraph")
    monkeypatch.setattr(factory.settings, "CHUNKING_OVERLAP_ENABLED", False)
    monkeypatch.setattr(factory.settings, "CHUNKING_OVERLAP_TOKENS", 7)
    monkeypatch.setattr(factory, "create_system_embedding_client", lambda: _FakeEmbedder())

    engine = factory.create_chunking_engine()

    assert isinstance(engine.chunker, StructuredSemanticChunker)
    assert engine.chunker.semantic_chunker.semantic_unit == "paragraph"
    assert engine.chunker.semantic_chunker.overlapper.effective_tokens == 0
    assert engine.chunker.semantic_chunker.overlapper.config.tokens == 7
