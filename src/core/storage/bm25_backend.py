"""BM25 全文检索后端工厂：按配置分发 Qdrant / Manticore。

写入侧（indexing pipeline）与召回侧（recall backend）各一个工厂。各后端实现鸭子
兼容（方法签名一致），调用方拿到的对象接口相同——切换后端只改 ``BM25_BACKEND``。
延迟 import 各后端，避免未启用后端的依赖在装配期被加载。配置错误必须立即失败，
否则会出现“写到一个后端、读另一个后端”的隐蔽数据不一致。

- ``qdrant``：sparse vector + ``Modifier.IDF`` 真 BM25，按 user 哈希分桶（128 桶
  共享 IDF 统计），类型加权用 Formula Query 乘法（``BM25_TYPE_MULT``）。
- ``manticore``（实验性）：coarse-only 原生 ``bm25a()``，按 dataset_id 精确建表
  （IDF/avgdl 天然只统计这个 dataset 自己的语料，不需要额外 tenant filter），类型
  加权在应用层按 ``BM25_TYPE_MULT`` 对候选池重排。
"""

from __future__ import annotations

from typing import Any

from src.config import settings

_QDRANT = "qdrant"
_MANTICORE = "manticore"
_SUPPORTED = frozenset({_QDRANT, _MANTICORE})


def _backend() -> str:
    backend = (settings.BM25_BACKEND or "").strip().lower()
    if backend not in _SUPPORTED:
        supported = ", ".join(sorted(_SUPPORTED))
        raise ValueError(f"Unsupported BM25_BACKEND={backend!r}; expected one of: {supported}")
    return backend


def _write_backends() -> list[str]:
    configured = getattr(settings, "BM25_WRITE_BACKENDS", "") or ""
    backends = [part.strip().lower() for part in configured.split(",") if part.strip()]
    return list(dict.fromkeys(backends)) or [_backend()]


def _build_indexing_backend(
    backend: str,
    *,
    chunk_repository: Any,
    update_chunk_status: bool,
) -> Any:
    if backend == _QDRANT:
        from src.core.storage.qdrant_bm25 import QdrantBm25IndexingPipeline

        return QdrantBm25IndexingPipeline(
            chunk_repository=chunk_repository,
            update_chunk_status=update_chunk_status,
        )
    if backend == _MANTICORE:
        from src.core.storage.manticore_bm25 import ManticoreBm25IndexingPipeline

        return ManticoreBm25IndexingPipeline(
            chunk_repository=chunk_repository,
            update_chunk_status=update_chunk_status,
        )
    raise ValueError(f"Unsupported BM25 write backend: {backend!r}")


def build_indexing_pipeline(*, chunk_repository: Any = None) -> Any:
    """返回 BM25 写入管线（鸭子兼容 ``write_es_index`` / ``delete_document_index``）。"""
    backends = _write_backends()
    if len(backends) == 1:
        return _build_indexing_backend(
            backends[0],
            chunk_repository=chunk_repository,
            update_chunk_status=True,
        )

    from src.core.storage.bm25_migration import DualWriteBm25IndexingPipeline

    children = {
        backend: _build_indexing_backend(
            backend,
            chunk_repository=chunk_repository,
            update_chunk_status=False,
        )
        for backend in backends
    }
    return DualWriteBm25IndexingPipeline(
        pipelines=children,
        chunk_repository=chunk_repository,
    )


def _build_recall_backend(backend: str) -> Any:
    if backend == _QDRANT:
        from src.core.storage.qdrant_bm25 import QdrantBm25Retriever

        return QdrantBm25Retriever()
    if backend == _MANTICORE:
        from src.core.storage.manticore_bm25 import ManticoreBm25Retriever

        return ManticoreBm25Retriever()
    raise ValueError(f"Unsupported BM25 recall backend: {backend!r}")


def build_bm25_recall_backend() -> Any:
    """返回 BM25 召回后端（鸭子兼容 ``recall_topk_chunks``）。"""
    backend = _backend()
    primary = _build_recall_backend(backend)
    shadow_backend = getattr(settings, "BM25_SHADOW_BACKEND", None)
    sample_rate = float(getattr(settings, "BM25_SHADOW_SAMPLE_RATE", 0.0))
    if shadow_backend is None or sample_rate <= 0:
        return primary

    from src.core.storage.bm25_migration import ShadowComparingBm25Retriever

    return ShadowComparingBm25Retriever(
        primary=primary,
        shadow=_build_recall_backend(shadow_backend),
        primary_name=backend,
        shadow_name=shadow_backend,
        sample_rate=sample_rate,
        timeout_seconds=float(settings.BM25_SHADOW_TIMEOUT_SECONDS),
    )
