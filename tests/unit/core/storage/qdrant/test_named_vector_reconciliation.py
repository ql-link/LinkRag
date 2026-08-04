"""Qdrant reconciliation 原语：按 named vector 探测与精确删除。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.storage.qdrant import QdrantIndexStore
from src.core.storage.qdrant.exceptions import QdrantStoreError


class _FakeClient:
    def __init__(self, vectors_by_point: dict[str, dict[str, object]], *, exists: bool = True):
        self.exists = exists
        self.vectors_by_point = vectors_by_point
        self.retrieve_calls: list[dict] = []
        self.delete_calls: list[dict] = []

    async def collection_exists(self, *, collection_name: str) -> bool:
        return self.exists

    async def retrieve(self, **kwargs):
        self.retrieve_calls.append(kwargs)
        requested = set(kwargs["with_vectors"])
        return [
            SimpleNamespace(
                id=chunk_id,
                vector={
                    name: value
                    for name, value in self.vectors_by_point[chunk_id].items()
                    if name in requested
                },
            )
            for chunk_id in kwargs["ids"]
            if chunk_id in self.vectors_by_point
        ]

    async def delete_vectors(self, **kwargs) -> None:
        self.delete_calls.append(kwargs)
        for chunk_id in kwargs["points"]:
            vectors = self.vectors_by_point.get(chunk_id)
            if vectors is None:
                continue
            for vector_name in kwargs["vectors"]:
                vectors.pop(vector_name, None)


async def test_presence_requires_target_named_vector_not_just_point() -> None:
    fake = _FakeClient(
        {
            "payload-only": {},
            "hybrid": {"dense": [0.1, 0.2], "sparse_text": {"indices": [1]}},
            "sparse-only": {"sparse_text": {"indices": [2]}},
        }
    )
    store = QdrantIndexStore(client=fake)

    result = await store.get_named_vector_presence(
        chunk_ids=["payload-only", "hybrid", "sparse-only", "missing-point"],
        vector_name="dense",
    )

    assert result == {
        "payload-only": False,
        "hybrid": True,
        "sparse-only": False,
        "missing-point": False,
    }
    assert fake.retrieve_calls[0]["with_vectors"] == ["dense"]
    assert fake.retrieve_calls[0]["with_payload"] is False


async def test_delete_named_vectors_preserves_point_payload_and_sibling_vector() -> None:
    fake = _FakeClient({"c1": {"dense": [0.1], "sparse_text": {"indices": [1], "values": [0.5]}}})
    store = QdrantIndexStore(client=fake)

    await store.delete_named_vectors(
        chunk_ids=["c1"],
        vector_name="dense",
    )
    # 重复清理同一路仍然成功。
    await store.delete_named_vectors(
        chunk_ids=["c1", "already-missing-point"],
        vector_name="dense",
    )

    assert "c1" in fake.vectors_by_point
    assert fake.vectors_by_point["c1"] == {"sparse_text": {"indices": [1], "values": [0.5]}}
    assert all(call["vectors"] == ["dense"] for call in fake.delete_calls)


async def test_missing_collection_is_idempotent_for_presence_and_delete() -> None:
    fake = _FakeClient({}, exists=False)
    store = QdrantIndexStore(client=fake)

    result = await store.get_named_vector_presence(
        chunk_ids=["c1"],
        vector_name="dense",
    )
    await store.delete_named_vectors(
        chunk_ids=["c1"],
        vector_name="dense",
    )

    assert result == {"c1": False}
    assert fake.retrieve_calls == []
    assert fake.delete_calls == []


class _ErrorClient:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def collection_exists(self, *, collection_name: str) -> bool:
        return True

    async def retrieve(self, **kwargs):
        raise self.error

    async def delete_vectors(self, **kwargs):
        raise self.error


async def test_missing_named_vector_schema_is_treated_as_absent_and_delete_success() -> None:
    store = QdrantIndexStore(client=_ErrorClient(RuntimeError("Not existing vector name dense")))

    assert await store.get_named_vector_presence(
        chunk_ids=["c1"],
        vector_name="dense",
    ) == {"c1": False}
    await store.delete_named_vectors(
        chunk_ids=["c1"],
        vector_name="dense",
    )


async def test_collection_removed_after_check_is_idempotent() -> None:
    store = QdrantIndexStore(client=_ErrorClient(RuntimeError("Collection chunks doesn't exist")))

    assert await store.get_named_vector_presence(
        chunk_ids=["c1"],
        vector_name="dense",
    ) == {"c1": False}
    await store.delete_named_vectors(
        chunk_ids=["c1"],
        vector_name="dense",
    )


async def test_unexpected_presence_error_is_wrapped() -> None:
    store = QdrantIndexStore(client=_ErrorClient(RuntimeError("transport exploded")))

    with pytest.raises(QdrantStoreError, match="Failed to inspect named vector"):
        await store.get_named_vector_presence(
            chunk_ids=["c1"],
            vector_name="dense",
        )
