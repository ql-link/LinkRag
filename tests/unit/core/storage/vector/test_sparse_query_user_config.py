# -*- coding: utf-8 -*-
"""Sparse 召回只接受 Dataset context 已解析的模型。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.config import settings
from src.core.pipeline.recall.exceptions import RecallFatalError
from src.core.storage.vector.exceptions import VectorRetrievalUserConfigMissingError
from src.core.storage.vector.facade import VectorStorageFacade
from src.core.storage.vector.sparse_retriever import SparseRetriever
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
    )

    result = await facade.search_sparse_chunks(query="   ", user_id=7, set_id=1)

    assert result.top_k == 4


class _FakeBackend:
    async def search_sparse_chunks(self, **kwargs):
        raise VectorRetrievalUserConfigMissingError("user 7 has no default SPARSE_EMBEDDING config")


@pytest.mark.asyncio
async def test_sparse_retriever_maps_to_recall_fatal():
    retriever = SparseRetriever(backend=_FakeBackend())
    with pytest.raises(RecallFatalError):
        await retriever.recall("q", [1], None, user_id=7, top_k=3)
