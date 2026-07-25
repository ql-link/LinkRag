# -*- coding: utf-8 -*-
"""Dense 召回只接受 Dataset context 已解析的模型。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.core.pipeline.recall.exceptions import RecallFatalError
from src.core.storage.vector.dense_retriever import DenseRetriever
from src.core.storage.vector.exceptions import VectorRetrievalUserConfigMissingError
from src.core.storage.vector.facade import VectorStorageFacade


@pytest.mark.asyncio
async def test_facade_default_top_k_uses_dense_retrieval_not_recall(monkeypatch):
    """dense facade 直调未传 top_k 时只读 DENSE_RETRIEVAL_TOP_K，不读 RECALL_DENSE_TOP_K。"""
    from src.config import settings

    monkeypatch.setattr(settings, "DENSE_RETRIEVAL_TOP_K", 3)
    monkeypatch.setattr(settings, "RECALL_DENSE_TOP_K", 100)
    facade = VectorStorageFacade(
        storage_service=MagicMock(),
        management_service=MagicMock(),
        compensation_service=MagicMock(),
        qdrant_store=MagicMock(),
        embedding_pipeline=None,
    )

    result = await facade.search_dense_chunks(query="   ", user_id=7, set_id=1)

    assert result.top_k == 3


class _FakeBackend:
    async def search_dense_chunks(self, **kwargs):
        raise VectorRetrievalUserConfigMissingError("user 7 has no default EMBEDDING config")


@pytest.mark.asyncio
async def test_dense_retriever_maps_to_recall_fatal():
    retriever = DenseRetriever(backend=_FakeBackend())
    with pytest.raises(RecallFatalError):
        await retriever.recall("q", [1], None, user_id=7, top_k=3)
