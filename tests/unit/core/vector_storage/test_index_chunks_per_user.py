"""LINK-91：VectorStoragePipeline.index_chunks 按发起用户解析 embedder 的单测。

钉住三条关键行为：
- 用户无默认 EMBEDDING 配置：DenseEmbeddingConfigMissingError 在 embed 前直接上抛，
  不触碰任何 chunk 状态（mark_indexing 不被调用）。
- 用户模型维度与系统统一维度不一致：标失败后抛 DenseEmbeddingDimensionError。
- 维度匹配：正常写入，并落库用户实际模型名。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import src.core.vector_storage.pipeline as pipeline_module
from src.core.splitter.factory import (
    DenseEmbeddingConfigMissingError,
    DenseEmbeddingDimensionError,
)
from src.core.splitter.models import EmbeddedChunk
from src.core.vector_storage.pipeline import VectorStoragePipeline


class _FakeUserPipeline:
    """伪装按用户解析出的 ChunkEmbeddingPipeline，控制输出向量维度与模型名。"""

    def __init__(self, *, dim: int, model: str = "user-embed", batch_size: int = 32) -> None:
        self.batch_size = batch_size
        self.embedding_model = model
        self._dim = dim
        self.last_stats = SimpleNamespace(embedding_model=model)

    async def aembed_chunks(self, chunks):
        return [
            EmbeddedChunk(
                chunk=chunk,
                embedding=[0.0] * self._dim,
                embedding_model=self.embedding_model,
            )
            for chunk in chunks
        ]


def _build_pipeline(
    mock_session_factory, mock_draft_factory, mock_repository, mock_qdrant_store
) -> VectorStoragePipeline:
    return VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=SimpleNamespace(batch_size=32),  # 系统管线，写入路径不再使用
    )


@pytest.mark.asyncio
async def test_index_chunks_config_missing_propagates_without_touching_chunks(
    monkeypatch,
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    failed_chunk_record,
):
    monkeypatch.setattr(
        pipeline_module,
        "aresolve_user_chunk_embedding_pipeline",
        AsyncMock(side_effect=DenseEmbeddingConfigMissingError(7)),
    )
    pipeline = _build_pipeline(
        mock_session_factory, mock_draft_factory, mock_repository, mock_qdrant_store
    )

    with pytest.raises(DenseEmbeddingConfigMissingError):
        await pipeline.index_chunks(
            user_id=7, set_id=1, doc_id=2, chunks=[failed_chunk_record]
        )

    # 配置缺失在 embed 前抛出：不触碰任何 chunk 状态，也不写 Qdrant。
    mock_repository.mark_indexing.assert_not_called()
    mock_qdrant_store.ensure_collection.assert_not_called()


@pytest.mark.asyncio
async def test_index_chunks_dimension_mismatch_raises_and_marks_failed(
    monkeypatch,
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    failed_chunk_record,
):
    monkeypatch.setattr(
        pipeline_module,
        "aresolve_user_chunk_embedding_pipeline",
        AsyncMock(return_value=_FakeUserPipeline(dim=2)),
    )
    monkeypatch.setattr(pipeline_module.settings, "DENSE_VECTOR_DIMENSION", 1024)
    mock_repository.mark_indexing = AsyncMock(return_value=1)
    pipeline = _build_pipeline(
        mock_session_factory, mock_draft_factory, mock_repository, mock_qdrant_store
    )

    with pytest.raises(DenseEmbeddingDimensionError):
        await pipeline.index_chunks(
            user_id=7, set_id=1, doc_id=2, chunks=[failed_chunk_record]
        )

    # 维度不符：当前批标失败，且不写 Qdrant。
    mock_repository.mark_failed.assert_awaited()
    mock_qdrant_store.upsert_points.assert_not_called()


@pytest.mark.asyncio
async def test_index_chunks_dimension_match_indexes_with_user_model(
    monkeypatch,
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    failed_chunk_record,
):
    monkeypatch.setattr(
        pipeline_module,
        "aresolve_user_chunk_embedding_pipeline",
        AsyncMock(return_value=_FakeUserPipeline(dim=2, model="user-embed-model")),
    )
    monkeypatch.setattr(pipeline_module.settings, "DENSE_VECTOR_DIMENSION", 2)
    mock_repository.mark_indexing = AsyncMock(return_value=1)
    mock_repository.mark_indexed = AsyncMock(return_value=1)
    pipeline = _build_pipeline(
        mock_session_factory, mock_draft_factory, mock_repository, mock_qdrant_store
    )

    result = await pipeline.index_chunks(
        user_id=7, set_id=1, doc_id=2, chunks=[failed_chunk_record]
    )

    assert result.indexed_chunks == 1
    assert result.total_chunks == 1
    assert result.embedding_model == "user-embed-model"
    mock_qdrant_store.ensure_collection.assert_awaited()
    mock_qdrant_store.upsert_points.assert_awaited()
