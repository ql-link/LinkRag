"""VectorStorageManagementPipeline 的稀疏向量 per-user 解析单测。

management 的 update_chunk 端到端流程由集成测试覆盖；本文件聚焦本次新增的
``_resolve_sparse_vector_service``（与 compensation 同构）：注入优先 + 按数据集解析。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.core.storage.vector.management_pipeline as mgmt_module
from src.core.storage.vector.exceptions import ChunkStructuralUpdateNotAllowedError


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


@pytest.mark.parametrize(
    ("field_name", "new_value"),
    [("start_line", 11), ("end_line", 21), ("chunk_index", 4)],
)
@pytest.mark.asyncio
async def test_update_chunk_rejects_structural_change_before_any_mutation(field_name, new_value):
    repository = AsyncMock()
    repository.get_updatable_by_chunk_ids.return_value = [
        SimpleNamespace(
            chunk_id="chunk-1",
            chunk_type="paragraph",
            start_line=10,
            end_line=20,
            chunk_index=3,
        )
    ]
    qdrant_store = AsyncMock()
    pipe = _pipeline(repository=repository, qdrant_store=qdrant_store)
    request = mgmt_module.ChunkUpdateRequest(chunk_id="chunk-1", content="updated")
    setattr(request, field_name, new_value)

    with pytest.raises(ChunkStructuralUpdateNotAllowedError) as exc_info:
        await pipe.update_chunk(request)

    assert exc_info.value.fields == {field_name}
    repository.update_chunk_metadata.assert_not_called()
    repository.update_chunk_for_reindex.assert_not_called()
    qdrant_store.upsert_points.assert_not_called()


@pytest.mark.asyncio
async def test_update_chunk_allows_equal_structural_fields_to_continue():
    pipe = _pipeline()
    record = SimpleNamespace(
        chunk_id="chunk-1",
        chunk_type="paragraph",
        start_line=10,
        end_line=20,
        chunk_index=3,
        dense_vector_status="SUCCESS",
        content_hash=pipe._content_hash("same"),
        content="same",
    )
    repository = AsyncMock()
    repository.get_updatable_by_chunk_ids.return_value = [record]
    pipe.repository = repository

    result = await pipe.update_chunk(
        mgmt_module.ChunkUpdateRequest(
            chunk_id="chunk-1",
            content="same",
            start_line=10,
            end_line=20,
            chunk_index=3,
        )
    )

    assert result.affected_chunks == 0
    assert result.skipped_chunk_ids == ["chunk-1"]


@pytest.mark.asyncio
async def test_mark_removed_deletes_wiki_refs_in_same_transaction_callback():
    repository = AsyncMock()
    repository.mark_removed.return_value = 2
    wiki_repository = AsyncMock()
    pipe = _pipeline(repository=repository, wiki_repository=wiki_repository)
    session = object()

    async def run(operation):
        return await operation(session)

    pipe._run_in_transaction_with_result = run

    assert await pipe._mark_removed(["c1", "c2"]) == 2
    repository.mark_removed.assert_awaited_once_with(
        session,
        ("c1", "c2"),
        expected_lifecycle_status="ACTIVE",
    )
    wiki_repository.delete_refs_by_chunk_ids.assert_awaited_once_with(session, ("c1", "c2"))


@pytest.mark.asyncio
async def test_mark_removed_aborts_before_wiki_delete_on_partial_cas():
    repository = AsyncMock()
    repository.mark_removed.return_value = 1
    wiki_repository = AsyncMock()
    pipe = _pipeline(repository=repository, wiki_repository=wiki_repository)
    session = object()

    async def run(operation):
        return await operation(session)

    pipe._run_in_transaction_with_result = run

    with pytest.raises(RuntimeError, match="CAS mismatch"):
        await pipe._mark_removed(["c1", "c2"])

    wiki_repository.delete_refs_by_chunk_ids.assert_not_awaited()
