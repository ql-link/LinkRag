"""BM25 工厂固定装配 Manticore。"""

from __future__ import annotations

from src.core.storage import bm25_backend
from src.core.storage.manticore_bm25 import (
    ManticoreBm25IndexingPipeline,
    ManticoreBm25Retriever,
)


def test_indexing_factory_returns_manticore() -> None:
    assert isinstance(bm25_backend.build_indexing_pipeline(), ManticoreBm25IndexingPipeline)


def test_recall_factory_returns_manticore() -> None:
    assert isinstance(bm25_backend.build_bm25_recall_backend(), ManticoreBm25Retriever)
