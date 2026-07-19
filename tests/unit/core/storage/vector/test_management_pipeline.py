"""VectorStorageManagementPipeline 的稀疏向量 per-user 解析单测。

management 的 update_chunk 端到端流程由集成测试覆盖；本文件聚焦本次新增的
``_resolve_sparse_vector_service``（与 compensation 同构）：注入优先 + 按数据集解析。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.core.storage.vector.management_pipeline as mgmt_module


def _pipeline(**over):
    kwargs = dict(
        session_factory=MagicMock(),
        repository=MagicMock(),
        qdrant_store=MagicMock(),
        embedding_pipeline=MagicMock(),
    )
    kwargs.update(over)
    return mgmt_module.VectorStorageManagementPipeline(**kwargs)


@pytest.mark.asyncio
async def test_resolve_sparse_service_prefers_explicit_dataset_service():
    injected = SimpleNamespace(model_name="injected")
    pipe = _pipeline(sparse_vector_service=injected)

    assert await pipe._resolve_sparse_vector_service(5, 9) is injected


@pytest.mark.asyncio
async def test_resolve_sparse_service_rejects_implicit_runtime_resolution():
    pipe = _pipeline()

    with pytest.raises(RuntimeError, match="explicitly injected dataset sparse"):
        await pipe._resolve_sparse_vector_service(42, 9)


@pytest.mark.parametrize("chunk_type", ["text", "hr", "unknown"])
def test_validate_chunk_type_rejects_unsupported_values(chunk_type):
    pipe = _pipeline()

    with pytest.raises(ValueError, match="Unsupported chunk_type"):
        pipe._validate_chunk_type(chunk_type)


def test_validate_chunk_type_accepts_front_matter():
    pipe = _pipeline()

    pipe._validate_chunk_type("front_matter")


@pytest.mark.parametrize("chunk_type", ["text", "hr"])
@pytest.mark.asyncio
async def test_update_chunk_rejects_disallowed_chunk_type_before_repository_update(chunk_type):
    repository = AsyncMock()
    repository.get_updatable_by_chunk_ids.return_value = [
        SimpleNamespace(chunk_id="chunk-1", chunk_type="paragraph")
    ]
    pipe = _pipeline(repository=repository)

    with pytest.raises(ValueError, match="Unsupported chunk_type"):
        await pipe.update_chunk(
            mgmt_module.ChunkUpdateRequest(
                chunk_id="chunk-1",
                content="updated",
                chunk_type=chunk_type,
            )
        )

    repository.update_chunk_metadata.assert_not_called()
    repository.update_chunk_for_reindex.assert_not_called()
