"""BM25 全文检索后端工厂：按 ``settings.BM25_BACKEND`` 分发 es / qdrant。

写入侧（indexing pipeline）与召回侧（recall backend）各一个工厂。两后端实现鸭子
兼容（方法签名一致），调用方拿到的对象接口相同——切换后端只改 ``BM25_BACKEND``，
回退到 ``es`` 零代码改动。延迟 import 各后端，避免未启用后端的依赖在装配期被加载。

- ``es``：Elasticsearch，类型加权用 ``constant_score`` 加法（``BM25_TYPE_BOOST``）。
- ``qdrant``：sparse vector + ``Modifier.IDF`` 真 BM25，类型加权用 Formula Query
  乘法（``BM25_TYPE_MULT``）。
"""

from __future__ import annotations

from typing import Any

from src.config import settings

_QDRANT = "qdrant"


def _backend() -> str:
    return (settings.BM25_BACKEND or "es").strip().lower()


def build_indexing_pipeline(*, chunk_repository: Any = None) -> Any:
    """返回 BM25 写入管线（鸭子兼容 ``write_es_index`` / ``delete_document_index``）。"""
    backend = _backend()
    if backend == _QDRANT:
        from src.core.storage.qdrant_bm25 import QdrantBm25IndexingPipeline

        return QdrantBm25IndexingPipeline(chunk_repository=chunk_repository)
    from src.core.storage.es import EsIndexingPipeline

    return EsIndexingPipeline(chunk_repository=chunk_repository)


def build_bm25_recall_backend() -> Any:
    """返回 BM25 召回后端（鸭子兼容 ``recall_topk_chunks``）。"""
    backend = _backend()
    if backend == _QDRANT:
        from src.core.storage.qdrant_bm25 import QdrantBm25Retriever

        return QdrantBm25Retriever()
    from src.core.storage.es import EsBm25Retriever

    return EsBm25Retriever()
