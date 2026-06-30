# -*- coding: utf-8 -*-
"""召回 sparse query 编码按用户模型解析 + 缺配置硬失败链路（dense 版的对偶）。

- facade.search_sparse_chunks 注入 query_sparse_resolver 时按 user_id 解析；resolver 抛
  SparseEmbeddingConfigMissingError → 翻成 VectorRetrievalUserConfigMissingError。
- 解析出的 service 真正用于 query 编码，且 resolver 按发起 user_id 调用。
- SparseRetriever 捕获该异常 → 抛 RecallFatalError（供 pipeline 硬失败，不静默降级）。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import settings
from src.core.encoding.sparse.factory import SparseEmbeddingConfigMissingError
from src.core.encoding.sparse.models import SparseVector
from src.core.pipeline.recall.exceptions import RecallFatalError
from src.core.storage.vector.exceptions import VectorRetrievalUserConfigMissingError
from src.core.storage.vector.facade import VectorStorageFacade
from src.core.storage.vector.sparse_retriever import SparseRetriever


def _facade_with_resolver(resolver, *, qdrant_store=None):
    # 召回装配：只注入 query_sparse_resolver、不注入 sparse_vector_service（与生产对齐）。
    return VectorStorageFacade(
        storage_service=MagicMock(),
        management_service=MagicMock(),
        compensation_service=MagicMock(),
        qdrant_store=qdrant_store or MagicMock(),
        sparse_vector_service=None,
        query_sparse_resolver=resolver,
    )


@pytest.mark.asyncio
async def test_facade_missing_user_sparse_config_translates(monkeypatch):
    monkeypatch.setattr(settings, "SPARSE_VECTOR_ENABLED", True)

    async def _resolver(user_id):
        raise SparseEmbeddingConfigMissingError(user_id)

    facade = _facade_with_resolver(_resolver)
    with pytest.raises(VectorRetrievalUserConfigMissingError):
        await facade.search_sparse_chunks(query="q", user_id=7, set_id=1, top_k=3)


@pytest.mark.asyncio
async def test_facade_default_top_k_uses_sparse_retrieval_not_recall(monkeypatch):
    """sparse facade 直调未传 top_k 时只读 SPARSE_RETRIEVAL_TOP_K，不读 RECALL_SPARSE_TOP_K。"""
    monkeypatch.setattr(settings, "SPARSE_VECTOR_ENABLED", True)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_TOP_K", 4)
    monkeypatch.setattr(settings, "RECALL_SPARSE_TOP_K", 50)

    facade = VectorStorageFacade(
        storage_service=MagicMock(),
        management_service=MagicMock(),
        compensation_service=MagicMock(),
        qdrant_store=MagicMock(),
        sparse_vector_service=None,
        query_sparse_resolver=None,
    )

    result = await facade.search_sparse_chunks(query="   ", user_id=7, set_id=1)

    assert result.top_k == 4


@pytest.mark.asyncio
async def test_facade_resolves_sparse_per_user_and_uses_it(monkeypatch):
    monkeypatch.setattr(settings, "SPARSE_VECTOR_ENABLED", True)

    service = SimpleNamespace(
        model_name="user-bge-m3",
        vector_name="sparse_text",
        vectorize_query=AsyncMock(return_value=SparseVector(indices=[1, 2], values=[0.5, 0.3])),
    )
    resolver = AsyncMock(return_value=service)

    qdrant_store = MagicMock()
    qdrant_store.bucket_router.route_user = MagicMock(return_value=SimpleNamespace(bucket_id=4))
    qdrant_store._search_chunks = AsyncMock(return_value=[])

    facade = _facade_with_resolver(resolver, qdrant_store=qdrant_store)
    result = await facade.search_sparse_chunks(query="hello", user_id=7, set_id=1, top_k=3)

    resolver.assert_awaited_once_with(7, 1)  # 按发起用户 + 数据集解析
    service.vectorize_query.assert_awaited_once_with("hello")  # 用解析出的 service 编码
    assert result.model_name == "user-bge-m3"
    assert result.vector_kind == "sparse"


class _FakeBackend:
    async def search_sparse_chunks(self, **kwargs):
        raise VectorRetrievalUserConfigMissingError("user 7 has no default SPARSE_EMBEDDING config")


@pytest.mark.asyncio
async def test_sparse_retriever_maps_to_recall_fatal():
    retriever = SparseRetriever(backend=_FakeBackend())
    with pytest.raises(RecallFatalError):
        await retriever.recall("q", [1], None, user_id=7, top_k=3)
