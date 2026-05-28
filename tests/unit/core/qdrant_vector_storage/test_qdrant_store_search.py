"""QdrantIndexStore._search_chunks 单测。

覆盖向量类型无关搜索底座的契约：
- collection 不存在 → 返空 hits（不抛）
- named sparse vector 不存在（关键词匹配）→ 返空 hits（不抛）
- query_points 入参形态：collection_name / query / using / query_filter / limit /
  score_threshold / with_payload=True
- ScoredPoint → VectorSearchHit 字段映射正确
- 网络异常 / collection_exists 失败 → QdrantStoreError
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.qdrant_vector_storage import BucketRouter, QdrantIndexStore
from src.core.qdrant_vector_storage.exceptions import QdrantStoreError
from src.core.qdrant_vector_storage.models import SparseQueryVectorSpec
from src.core.vector_storage.models import VectorSearchHit


class FakeModels:
    """qdrant_client.models 的最小测试替身——只覆盖 _search_chunks 用到的类型。"""

    class SparseVector:
        def __init__(self, *, indices, values) -> None:
            self.indices = indices
            self.values = values

    class FieldCondition:  # 由 facade 构造，store 透传，这里仅为类型存在
        pass

    class Filter:
        pass


class _SearchableQdrantIndexStore(QdrantIndexStore):
    """注入 FakeModels；其它行为继承自真实类。"""

    def _models(self):
        return FakeModels


def _store(client: AsyncMock) -> _SearchableQdrantIndexStore:
    return _SearchableQdrantIndexStore(
        client=client,
        bucket_router=BucketRouter(bucket_count=1, prefix="test_bucket"),
    )


def _spec(*, vector_name: str = "sparse_text") -> SparseQueryVectorSpec:
    return SparseQueryVectorSpec(
        vector_name=vector_name,
        indices=[1, 5, 7],
        values=[0.4, 0.3, 0.2],
    )


def _payload_filter() -> object:
    """payload filter 由 facade 构造；这里给个 sentinel 以验证透传。"""
    return SimpleNamespace(_marker="payload-filter-sentinel")


def _scored_point(*, point_id: str, score: float, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(id=point_id, score=score, payload=payload)


@pytest.mark.asyncio
async def test_should_return_empty_hits_when_collection_does_not_exist():
    client = AsyncMock()
    client.collection_exists.return_value = False
    store = _store(client)

    hits = await store._search_chunks(
        bucket_id=0,
        query_vector_spec=_spec(),
        payload_filter=_payload_filter(),
        limit=10,
        score_threshold=0.0,
    )

    assert hits == []
    client.query_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_call_query_points_with_expected_arguments_when_collection_exists():
    client = AsyncMock()
    client.collection_exists.return_value = True
    payload = {"chunk_id": "c1", "doc_id": 42, "set_id": 99, "user_id": 1}
    client.query_points.return_value = SimpleNamespace(
        points=[_scored_point(point_id="c1", score=0.42, payload=payload)]
    )
    store = _store(client)
    payload_filter = _payload_filter()

    hits = await store._search_chunks(
        bucket_id=0,
        query_vector_spec=_spec(vector_name="sparse_text"),
        payload_filter=payload_filter,
        limit=20,
        score_threshold=0.3,
    )

    client.query_points.assert_awaited_once()
    call = client.query_points.await_args.kwargs
    assert call["collection_name"] == "test_bucket_0"
    assert call["using"] == "sparse_text"
    assert call["query_filter"] is payload_filter
    assert call["limit"] == 20
    assert call["score_threshold"] == 0.3
    assert call["with_payload"] is True
    assert call["with_vectors"] is False
    assert isinstance(call["query"], FakeModels.SparseVector)
    assert call["query"].indices == [1, 5, 7]
    assert call["query"].values == [0.4, 0.3, 0.2]

    assert hits == [
        VectorSearchHit(
            chunk_id="c1",
            doc_id=42,
            set_id=99,
            score=0.42,
            vector_kind="sparse",
        )
    ]


@pytest.mark.asyncio
async def test_should_map_multiple_scored_points_in_order():
    client = AsyncMock()
    client.collection_exists.return_value = True
    points = [
        _scored_point(point_id="c1", score=0.9, payload={"doc_id": 1, "set_id": 10}),
        _scored_point(point_id="c2", score=0.5, payload={"doc_id": 2, "set_id": 10}),
        _scored_point(point_id="c3", score=0.3, payload={"doc_id": 3, "set_id": 10}),
    ]
    client.query_points.return_value = SimpleNamespace(points=points)
    store = _store(client)

    hits = await store._search_chunks(
        bucket_id=0,
        query_vector_spec=_spec(),
        payload_filter=_payload_filter(),
        limit=10,
        score_threshold=0.0,
    )

    assert [h.chunk_id for h in hits] == ["c1", "c2", "c3"]
    assert all(h.vector_kind == "sparse" for h in hits)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_message",
    [
        "Named vector 'sparse_text' not found",
        "vector 'sparse_text' does not exist",
        "sparse vector not found in collection",
    ],
)
async def test_should_return_empty_hits_when_named_vector_is_missing(error_message: str):
    """1.17.1 SDK 没有专属异常类——通过消息关键词降级为空集。"""
    client = AsyncMock()
    client.collection_exists.return_value = True
    client.query_points.side_effect = RuntimeError(error_message)
    store = _store(client)

    hits = await store._search_chunks(
        bucket_id=0,
        query_vector_spec=_spec(),
        payload_filter=_payload_filter(),
        limit=10,
        score_threshold=0.0,
    )

    assert hits == []


@pytest.mark.asyncio
async def test_should_raise_qdrant_store_error_on_network_failure():
    """关键词不匹配的底层异常应当透传为 QdrantStoreError。"""
    client = AsyncMock()
    client.collection_exists.return_value = True
    client.query_points.side_effect = RuntimeError("connection reset by peer")
    store = _store(client)

    with pytest.raises(QdrantStoreError, match="Failed to query collection"):
        await store._search_chunks(
            bucket_id=0,
            query_vector_spec=_spec(),
            payload_filter=_payload_filter(),
            limit=10,
            score_threshold=0.0,
        )


@pytest.mark.asyncio
async def test_should_raise_qdrant_store_error_when_collection_exists_check_fails():
    client = AsyncMock()
    client.collection_exists.side_effect = RuntimeError("qdrant down")
    store = _store(client)

    with pytest.raises(QdrantStoreError, match="Failed to check collection existence"):
        await store._search_chunks(
            bucket_id=0,
            query_vector_spec=_spec(),
            payload_filter=_payload_filter(),
            limit=10,
            score_threshold=0.0,
        )


@pytest.mark.asyncio
async def test_should_handle_response_without_points_attribute_gracefully():
    """老/新 API 形态兼容性：response 直接是 list[ScoredPoint] 也应工作。"""
    client = AsyncMock()
    client.collection_exists.return_value = True
    client.query_points.return_value = [
        _scored_point(point_id="c1", score=0.7, payload={"doc_id": 1, "set_id": 10}),
    ]
    store = _store(client)

    hits = await store._search_chunks(
        bucket_id=0,
        query_vector_spec=_spec(),
        payload_filter=_payload_filter(),
        limit=10,
        score_threshold=0.0,
    )

    assert len(hits) == 1
    assert hits[0].chunk_id == "c1"


@pytest.mark.asyncio
async def test_should_default_payload_fields_when_payload_is_missing():
    """payload 缺失 doc_id / set_id 时降级到 0，避免 None 传染。"""
    client = AsyncMock()
    client.collection_exists.return_value = True
    client.query_points.return_value = SimpleNamespace(
        points=[_scored_point(point_id="c1", score=0.1, payload={})]
    )
    store = _store(client)

    hits = await store._search_chunks(
        bucket_id=0,
        query_vector_spec=_spec(),
        payload_filter=_payload_filter(),
        limit=10,
        score_threshold=0.0,
    )

    assert hits[0].doc_id == 0
    assert hits[0].set_id == 0
