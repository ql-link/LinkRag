"""VectorStorageFacade.search_sparse_chunks 单测。

覆盖召回入口的 acceptance.feature 22 个 Scenario 中的 21 条（最后一条
"调用方只通过 vector_storage 包接触召回 API" 在 ``test_public_api_surface``
里独立验证）：

- 主流程：合法 query 命中 + hit 字段强校验
- 参数处理：默认值合并 / per-call 覆盖 / 优先级
- 路由 + vector name 一致性
- payload filter 构造（user_id + set_id 必含、doc_id None / [] / 单值 / 多值）
- 异常路径：空 query 短路 / 参数越界 / SPARSE_VECTOR_ENABLED=False / encoder 失败
  / Qdrant 故障 / 配置错
- 只读语义
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import settings
from src.core.qdrant_vector_storage import BucketRoute
from src.core.qdrant_vector_storage.exceptions import (
    QdrantStoreError,
    QdrantVectorStorageConfigurationError,
)
from src.core.qdrant_vector_storage.models import SparseQueryVectorSpec
from src.core.sparse_vector import (
    SparseVector,
    SparseVectorConfigurationError,
    SparseVectorEncodingError,
    SparseVectorService,
)
from src.core.vector_storage import (
    VectorRetrievalBackendError,
    VectorRetrievalConfigurationError,
    VectorRetrievalEncodingError,
    VectorRetrievalError,
    VectorSearchHit,
    VectorSearchResult,
    VectorStorageFacade,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def enable_sparse_vector(monkeypatch):
    """召回入口默认开启 sparse；个别 Scenario 单独关闭。"""
    monkeypatch.setattr(settings, "SPARSE_VECTOR_ENABLED", True)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_TOP_K", 10)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_SCORE_THRESHOLD", 0.0)


@pytest.fixture
def fake_sparse_vector():
    return SparseVector(indices=[1, 5, 7], values=[0.4, 0.3, 0.2])


@pytest.fixture
def fake_sparse_service(fake_sparse_vector):
    """带 vector_name + model_name + vectorize_query 的最小 service 替身。"""
    service = MagicMock(spec=SparseVectorService)
    service.vector_name = "sparse_text"
    service.model_name = "bge-m3-fake"
    service.vectorize_query = AsyncMock(return_value=fake_sparse_vector)
    return service


@pytest.fixture
def fake_qdrant_store():
    """Qdrant store 替身：暴露 bucket_router + _search_chunks。"""
    store = MagicMock()
    bucket_router = MagicMock()
    bucket_router.route_user.return_value = BucketRoute(
        bucket_id=42, collection_name="kb_bucket_42",
    )
    store.bucket_router = bucket_router
    store._search_chunks = AsyncMock(return_value=[])
    store.close = AsyncMock()
    # 写入路径相关方法不会在召回路径触发；mock 出来仅防止误调用时崩
    store.upsert_points = AsyncMock(side_effect=AssertionError("upsert_points must not be called"))
    store.update_vectors = AsyncMock(side_effect=AssertionError("update_vectors must not be called"))
    store.delete_points = AsyncMock(side_effect=AssertionError("delete_points must not be called"))
    return store


@pytest.fixture
def facade(fake_qdrant_store, fake_sparse_service):
    return VectorStorageFacade(
        storage_service=AsyncMock(),
        management_service=AsyncMock(),
        compensation_service=AsyncMock(),
        qdrant_store=fake_qdrant_store,
        sparse_vector_service=fake_sparse_service,
    )


# ---------------------------------------------------------------------------
# 主流程：合法 query 命中并返回 top-k hits（Scenario 1）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_return_hits_with_required_fields_on_happy_path(
    facade, fake_qdrant_store, fake_sparse_service,
):
    fake_qdrant_store._search_chunks.return_value = [
        VectorSearchHit(chunk_id="c1", doc_id=10, set_id=20, score=0.9, vector_kind="sparse"),
        VectorSearchHit(chunk_id="c2", doc_id=11, set_id=20, score=0.5, vector_kind="sparse"),
    ]

    result = await facade.search_sparse_chunks(
        query="数据治理流程", user_id=10002, set_id=10003,
    )

    assert isinstance(result, VectorSearchResult)
    assert result.vector_kind == "sparse"
    assert result.vector_name == "sparse_text"
    assert result.model_name == "bge-m3-fake"
    assert len(result.hits) == 2
    for hit in result.hits:
        assert {f.name for f in hit.__dataclass_fields__.values()} == {
            "chunk_id", "doc_id", "set_id", "score", "vector_kind",
        }
        assert hit.vector_kind == "sparse"
    # 写入与查询使用相同的 vector name
    assert result.vector_name == fake_sparse_service.vector_name
    fake_sparse_service.vectorize_query.assert_awaited_once_with("数据治理流程")


@pytest.mark.asyncio
async def test_hit_dataclass_does_not_expose_payload_or_content_fields(facade):
    """Scenario 1 强校验：hit 不含 content / payload。"""
    field_names = {f.name for f in VectorSearchHit.__dataclass_fields__.values()}

    assert "payload" not in field_names
    assert "content" not in field_names


# ---------------------------------------------------------------------------
# 参数处理与默认值合并（Scenario 2 / 3 / 4）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_use_global_defaults_when_top_k_and_threshold_not_provided(
    facade, fake_qdrant_store,
):
    result = await facade.search_sparse_chunks(query="q", user_id=1, set_id=2)

    fake_qdrant_store._search_chunks.assert_awaited_once()
    call = fake_qdrant_store._search_chunks.await_args.kwargs
    assert call["limit"] == 10
    assert call["score_threshold"] == 0.0
    assert result.top_k == 10
    assert result.score_threshold == 0.0


@pytest.mark.asyncio
async def test_should_use_caller_overrides_when_top_k_and_threshold_provided(
    facade, fake_qdrant_store,
):
    result = await facade.search_sparse_chunks(
        query="q", user_id=1, set_id=2, top_k=20, score_threshold=0.3,
    )

    call = fake_qdrant_store._search_chunks.await_args.kwargs
    assert call["limit"] == 20
    assert call["score_threshold"] == 0.3
    assert result.top_k == 20
    assert result.score_threshold == 0.3


@pytest.mark.asyncio
async def test_should_prefer_per_call_top_k_over_global_default(facade, fake_qdrant_store, monkeypatch):
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_TOP_K", 10)

    result = await facade.search_sparse_chunks(query="q", user_id=1, set_id=2, top_k=5)

    assert fake_qdrant_store._search_chunks.await_args.kwargs["limit"] == 5
    assert result.top_k == 5


# ---------------------------------------------------------------------------
# Bucket 路由与 vector name 一致性（Scenario 5 / 6）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_route_via_shared_bucket_router(facade, fake_qdrant_store):
    await facade.search_sparse_chunks(query="q", user_id=10002, set_id=10003)

    fake_qdrant_store.bucket_router.route_user.assert_called_once_with(10002)
    assert fake_qdrant_store._search_chunks.await_args.kwargs["bucket_id"] == 42


@pytest.mark.asyncio
async def test_should_use_sparse_vector_name_from_service(facade, fake_qdrant_store):
    await facade.search_sparse_chunks(query="q", user_id=1, set_id=2)

    spec: SparseQueryVectorSpec = fake_qdrant_store._search_chunks.await_args.kwargs["query_vector_spec"]
    assert spec.vector_name == "sparse_text"


# ---------------------------------------------------------------------------
# Payload filter（Scenario 7 / 8 / 9 / 10 / 11）
# ---------------------------------------------------------------------------


def _filter_must_keys(payload_filter: Any) -> list[str]:
    """从 qdrant_client.models.Filter 提取 must FieldCondition.key 列表。"""
    return [cond.key for cond in payload_filter.must]


def _filter_must_by_key(payload_filter: Any, key: str) -> Any:
    for cond in payload_filter.must:
        if cond.key == key:
            return cond
    raise AssertionError(f"FieldCondition with key={key!r} not found in must")


@pytest.mark.asyncio
async def test_should_include_user_id_and_set_id_in_payload_filter(facade, fake_qdrant_store):
    await facade.search_sparse_chunks(query="q", user_id=10002, set_id=10003)

    payload_filter = fake_qdrant_store._search_chunks.await_args.kwargs["payload_filter"]
    keys = _filter_must_keys(payload_filter)
    assert "user_id" in keys
    assert "set_id" in keys
    assert "doc_id" not in keys
    assert _filter_must_by_key(payload_filter, "user_id").match.value == 10002
    assert _filter_must_by_key(payload_filter, "set_id").match.value == 10003


@pytest.mark.asyncio
@pytest.mark.parametrize("doc_id", [None, []])
async def test_should_omit_doc_id_filter_when_doc_id_is_none_or_empty(
    facade, fake_qdrant_store, doc_id,
):
    await facade.search_sparse_chunks(
        query="q", user_id=1, set_id=2, doc_id=doc_id,
    )

    payload_filter = fake_qdrant_store._search_chunks.await_args.kwargs["payload_filter"]
    assert "doc_id" not in _filter_must_keys(payload_filter)


@pytest.mark.asyncio
async def test_should_use_match_any_for_single_doc_id(facade, fake_qdrant_store):
    await facade.search_sparse_chunks(
        query="q", user_id=1, set_id=2, doc_id=[42],
    )

    payload_filter = fake_qdrant_store._search_chunks.await_args.kwargs["payload_filter"]
    cond = _filter_must_by_key(payload_filter, "doc_id")
    # MatchAny.any 必含给定列表
    assert list(cond.match.any) == [42]


@pytest.mark.asyncio
async def test_should_use_match_any_for_multiple_doc_ids(facade, fake_qdrant_store):
    await facade.search_sparse_chunks(
        query="q", user_id=1, set_id=2, doc_id=[42, 43, 44],
    )

    payload_filter = fake_qdrant_store._search_chunks.await_args.kwargs["payload_filter"]
    cond = _filter_must_by_key(payload_filter, "doc_id")
    assert list(cond.match.any) == [42, 43, 44]


# ---------------------------------------------------------------------------
# Score 过滤与排序（Scenario 12 / 13）
# 注：实际过滤在 Qdrant 端 + store 层；facade 单测只确认参数透传给 store。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_pass_score_threshold_to_store(facade, fake_qdrant_store):
    await facade.search_sparse_chunks(
        query="q", user_id=1, set_id=2, score_threshold=0.3,
    )

    assert fake_qdrant_store._search_chunks.await_args.kwargs["score_threshold"] == 0.3


@pytest.mark.asyncio
async def test_should_pass_limit_to_store(facade, fake_qdrant_store):
    await facade.search_sparse_chunks(query="q", user_id=1, set_id=2, top_k=5)

    assert fake_qdrant_store._search_chunks.await_args.kwargs["limit"] == 5


# ---------------------------------------------------------------------------
# 异常路径：空 query / 参数越界 / 配置错（Scenario 14 / 15 / 16）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", "   ", "\t", "\n", " \t \n "])
async def test_should_short_circuit_on_blank_query(
    facade, fake_qdrant_store, fake_sparse_service, query: str,
):
    result = await facade.search_sparse_chunks(query=query, user_id=1, set_id=2)

    assert result.hits == []
    fake_sparse_service.vectorize_query.assert_not_awaited()
    fake_qdrant_store._search_chunks.assert_not_awaited()
    fake_qdrant_store.bucket_router.route_user.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": "q", "user_id": 0, "set_id": 10003},
        {"query": "q", "user_id": -1, "set_id": 10003},
        {"query": "q", "user_id": 10002, "set_id": 0},
        {"query": "q", "user_id": 10002, "set_id": -1},
        {"query": "q", "user_id": 10002, "set_id": 10003, "top_k": 0},
        {"query": "q", "user_id": 10002, "set_id": 10003, "top_k": -3},
        {"query": "q", "user_id": 10002, "set_id": 10003, "score_threshold": -0.1},
    ],
)
async def test_should_raise_value_error_on_param_out_of_range(
    facade, fake_qdrant_store, fake_sparse_service, kwargs,
):
    with pytest.raises(ValueError):
        await facade.search_sparse_chunks(**kwargs)

    fake_sparse_service.vectorize_query.assert_not_awaited()
    fake_qdrant_store._search_chunks.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_raise_configuration_error_when_sparse_vector_disabled(
    fake_qdrant_store, fake_sparse_service, monkeypatch,
):
    monkeypatch.setattr(settings, "SPARSE_VECTOR_ENABLED", False)
    facade = VectorStorageFacade(
        storage_service=AsyncMock(),
        management_service=AsyncMock(),
        compensation_service=AsyncMock(),
        qdrant_store=fake_qdrant_store,
        sparse_vector_service=fake_sparse_service,
    )

    with pytest.raises(VectorRetrievalConfigurationError):
        await facade.search_sparse_chunks(query="q", user_id=1, set_id=2)

    fake_sparse_service.vectorize_query.assert_not_awaited()
    fake_qdrant_store._search_chunks.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_raise_configuration_error_when_service_not_injected(fake_qdrant_store):
    facade = VectorStorageFacade(
        storage_service=AsyncMock(),
        management_service=AsyncMock(),
        compensation_service=AsyncMock(),
        qdrant_store=fake_qdrant_store,
        sparse_vector_service=None,
    )

    with pytest.raises(VectorRetrievalConfigurationError):
        await facade.search_sparse_chunks(query="q", user_id=1, set_id=2)


# ---------------------------------------------------------------------------
# 异常路径：底层异常翻译（Scenario 19 / 20）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_translate_encoding_error_from_service(facade, fake_sparse_service):
    fake_sparse_service.vectorize_query.side_effect = SparseVectorEncodingError("bge-m3 down")

    with pytest.raises(VectorRetrievalEncodingError, match="bge-m3 down"):
        await facade.search_sparse_chunks(query="q", user_id=1, set_id=2)


@pytest.mark.asyncio
async def test_should_translate_configuration_error_from_service(facade, fake_sparse_service):
    fake_sparse_service.vectorize_query.side_effect = SparseVectorConfigurationError("missing dep")

    with pytest.raises(VectorRetrievalConfigurationError, match="missing dep"):
        await facade.search_sparse_chunks(query="q", user_id=1, set_id=2)


@pytest.mark.asyncio
async def test_should_translate_backend_error_from_store(facade, fake_qdrant_store):
    fake_qdrant_store._search_chunks.side_effect = QdrantStoreError("connection reset")

    with pytest.raises(VectorRetrievalBackendError, match="connection reset"):
        await facade.search_sparse_chunks(query="q", user_id=1, set_id=2)


@pytest.mark.asyncio
async def test_should_translate_qdrant_configuration_error_from_store(facade, fake_qdrant_store):
    fake_qdrant_store._search_chunks.side_effect = QdrantVectorStorageConfigurationError("no client")

    with pytest.raises(VectorRetrievalConfigurationError, match="no client"):
        await facade.search_sparse_chunks(query="q", user_id=1, set_id=2)


# ---------------------------------------------------------------------------
# 只读语义（Scenario 21）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_be_read_only_with_no_write_calls(facade, fake_qdrant_store, fake_sparse_service):
    """连续两次相同调用：bucket 路由稳定、不触发任何写入操作。"""
    await facade.search_sparse_chunks(query="q", user_id=1, set_id=2)
    await facade.search_sparse_chunks(query="q", user_id=1, set_id=2)

    assert fake_sparse_service.vectorize_query.await_count == 2
    assert fake_qdrant_store._search_chunks.await_count == 2
    # bucket_router 都用 user_id 计算同一 bucket
    assert fake_qdrant_store.bucket_router.route_user.call_count == 2
    # 写入路径方法被 fixture 装上 AssertionError side_effect；调用即崩
    fake_qdrant_store.upsert_points.assert_not_called()
    fake_qdrant_store.update_vectors.assert_not_called()
    fake_qdrant_store.delete_points.assert_not_called()


# ---------------------------------------------------------------------------
# 对外暴露面（Scenario 22）
# ---------------------------------------------------------------------------


def test_public_api_surface_only_exposes_intended_symbols():
    """Scenario 22：vector_storage 包是召回 API 单一 import 源；内部包装类不进 __all__。"""
    import src.core.vector_storage as vs

    # 必须暴露
    assert "VectorStorageFacade" in vs.__all__
    assert "VectorSearchHit" in vs.__all__
    assert "VectorSearchResult" in vs.__all__
    assert "VectorRetrievalError" in vs.__all__
    assert "VectorRetrievalConfigurationError" in vs.__all__
    assert "VectorRetrievalBackendError" in vs.__all__
    assert "VectorRetrievalEncodingError" in vs.__all__

    # 不允许暴露
    assert "SparseVectorSearchRequest" not in vs.__all__
    assert "QueryVectorSpec" not in vs.__all__
    assert "SparseQueryVectorSpec" not in vs.__all__

    # 异常族继承关系正确
    assert issubclass(VectorRetrievalConfigurationError, VectorRetrievalError)
    assert issubclass(VectorRetrievalBackendError, VectorRetrievalError)
    assert issubclass(VectorRetrievalEncodingError, VectorRetrievalError)
