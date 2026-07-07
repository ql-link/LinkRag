"""Manticore BM25 后端：按 dataset_id 物理建表，原生 bm25f 双字段真 BM25F（实验性）。

与 ``src/core/storage/es`` / ``src/core/storage/qdrant_bm25`` 对称，由
``src/core/storage/bm25_backend.py`` 工厂按 ``BM25_BACKEND=manticore`` 切换。

跟 Qdrant BM25 后端的核心差异是隔离粒度：Qdrant 按 user 哈希分桶（128 个桶共享，
IDF 统计范围收窄到"同桶用户"）；Manticore 按 dataset_id 精确建表，IDF 与 avgdl
天然只统计这一个 dataset 自己的语料，不存在跨租户统计漂移的问题。
"""

from .exceptions import ManticoreConfigurationError, ManticoreStoreError
from .pipeline import ManticoreBm25IndexingPipeline
from .retrieval import ManticoreBm25Retriever
from .store import Bm25Point, Bm25ScoredPoint, ManticoreBm25Store
from .table_router import TableRoute, TableRouter

__all__ = [
    "Bm25Point",
    "Bm25ScoredPoint",
    "ManticoreBm25IndexingPipeline",
    "ManticoreBm25Retriever",
    "ManticoreBm25Store",
    "ManticoreConfigurationError",
    "ManticoreStoreError",
    "TableRoute",
    "TableRouter",
]
