"""BM25 后端装配：生产统一使用 Manticore。"""

from __future__ import annotations

from typing import Any


def build_indexing_pipeline(*, chunk_repository: Any = None) -> Any:
    """返回唯一的 Manticore BM25 写入管线。"""
    from src.core.storage.manticore_bm25 import ManticoreBm25IndexingPipeline

    return ManticoreBm25IndexingPipeline(
        chunk_repository=chunk_repository,
        update_chunk_status=True,
    )


def build_bm25_recall_backend() -> Any:
    """返回唯一的 Manticore BM25 召回后端。"""
    from src.core.storage.manticore_bm25 import ManticoreBm25Retriever

    return ManticoreBm25Retriever()
