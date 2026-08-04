"""Manticore BM25 后端：按 dataset_id 物理建表，使用原生 BM25 排序。

由 ``src/core/storage/bm25_backend.py`` 统一装配。

Manticore 是当前唯一 BM25 后端。按 dataset_id 精确建表后，IDF 与 avgdl 只统计
当前 dataset 的语料，不存在跨租户统计漂移。
"""

from .exceptions import ManticoreConfigurationError, ManticoreStoreError
from .pipeline import ManticoreBm25IndexingPipeline
from .retrieval import ManticoreBm25Retriever
from .store import (
    Bm25Point,
    Bm25ScoredPoint,
    ManticoreBm25Store,
    close_manticore_bm25_store,
    get_manticore_bm25_store,
)
from .table_router import TableRoute, TableRouter

__all__ = [
    "Bm25Point",
    "Bm25ScoredPoint",
    "ManticoreBm25IndexingPipeline",
    "ManticoreBm25Retriever",
    "ManticoreBm25Store",
    "ManticoreConfigurationError",
    "ManticoreStoreError",
    "close_manticore_bm25_store",
    "get_manticore_bm25_store",
    "TableRoute",
    "TableRouter",
]
