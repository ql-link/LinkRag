"""BM25 后端工厂的配置分发边界。"""

from __future__ import annotations

import pytest

from src.core.storage import bm25_backend


def test_backend_normalizes_configured_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bm25_backend.settings, "BM25_BACKEND", " MANTICORE ")

    assert bm25_backend._backend() == "manticore"


@pytest.mark.parametrize("value", ["", "es", "elastic", "mantcore"])
def test_backend_rejects_invalid_value_without_silent_fallback(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setattr(bm25_backend.settings, "BM25_BACKEND", value)

    with pytest.raises(ValueError, match="Unsupported BM25_BACKEND"):
        bm25_backend._backend()


def test_write_backends_fall_back_to_read_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bm25_backend.settings, "BM25_BACKEND", "qdrant")
    monkeypatch.setattr(bm25_backend.settings, "BM25_WRITE_BACKENDS", "")

    assert bm25_backend._write_backends() == ["qdrant"]


def test_dual_write_factory_disables_child_status_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    def fake_builder(backend, *, chunk_repository, update_chunk_status):
        calls.append((backend, update_chunk_status))
        return object()

    monkeypatch.setattr(bm25_backend.settings, "BM25_WRITE_BACKENDS", "qdrant,manticore")
    monkeypatch.setattr(bm25_backend, "_build_indexing_backend", fake_builder)

    pipeline = bm25_backend.build_indexing_pipeline()

    assert pipeline.__class__.__name__ == "DualWriteBm25IndexingPipeline"
    assert calls == [("qdrant", False), ("manticore", False)]
