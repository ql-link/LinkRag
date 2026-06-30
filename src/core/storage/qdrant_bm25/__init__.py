"""Qdrant BM25 后端：以 sparse vector + ``Modifier.IDF`` 实现真 BM25（路 A），
召回时用 Formula Query 表达「BM25 主分 × chunk_type 乘数」的乘法类型加权。

与 ``src/core/storage/es`` 对称，由
``src/core/storage/bm25_backend.py`` 工厂按 ``BM25_BACKEND=qdrant`` 切换。
复用 ``src/core/storage/qdrant`` 的 client 约定（独立 collection，不寄生在
dense/sparse_text 的 per-bucket collection 上）。
"""

from .encoder import (
    Bm25SparseEncoder,
    EncodedSparseVector,
    build_encoder_from_settings,
    term_to_dimension,
)
from .pipeline import QdrantBm25IndexingPipeline
from .retrieval import QdrantBm25Retriever
from .store import Bm25Point, Bm25ScoredPoint, QdrantBm25Store

__all__ = [
    "Bm25Point",
    "Bm25ScoredPoint",
    "Bm25SparseEncoder",
    "EncodedSparseVector",
    "QdrantBm25IndexingPipeline",
    "QdrantBm25Retriever",
    "QdrantBm25Store",
    "build_encoder_from_settings",
    "term_to_dimension",
]
