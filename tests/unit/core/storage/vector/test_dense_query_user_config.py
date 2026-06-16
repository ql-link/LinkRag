# -*- coding: utf-8 -*-
"""召回 dense query 编码按用户模型解析 + 缺配置硬失败链路。

- facade.search_dense_chunks 注入 query_embedding_resolver 时按 user_id 解析；
  resolver 抛 DenseEmbeddingConfigMissingError → 翻成 VectorRetrievalUserConfigMissingError。
- DenseRetriever 捕获该异常 → 抛 RecallFatalError（供 pipeline 硬失败）。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.core.pipeline.recall.exceptions import RecallFatalError
from src.core.splitter.factory import DenseEmbeddingConfigMissingError
from src.core.storage.vector.dense_retriever import DenseRetriever
from src.core.storage.vector.exceptions import VectorRetrievalUserConfigMissingError
from src.core.storage.vector.facade import VectorStorageFacade


def _facade_with_resolver(resolver):
    return VectorStorageFacade(
        storage_service=MagicMock(),
        management_service=MagicMock(),
        compensation_service=MagicMock(),
        qdrant_store=MagicMock(),
        embedding_pipeline=None,
        query_embedding_resolver=resolver,
    )


@pytest.mark.asyncio
async def test_facade_missing_user_embedding_config_translates():
    async def _resolver(user_id):
        raise DenseEmbeddingConfigMissingError(user_id)

    facade = _facade_with_resolver(_resolver)
    with pytest.raises(VectorRetrievalUserConfigMissingError):
        await facade.search_dense_chunks(query="q", user_id=7, set_id=1, top_k=3)


class _FakeBackend:
    async def search_dense_chunks(self, **kwargs):
        raise VectorRetrievalUserConfigMissingError("user 7 has no default EMBEDDING config")


@pytest.mark.asyncio
async def test_dense_retriever_maps_to_recall_fatal():
    retriever = DenseRetriever(backend=_FakeBackend())
    with pytest.raises(RecallFatalError):
        await retriever.recall("q", [1], None, user_id=7, top_k=3)
