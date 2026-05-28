"""稀疏向量召回入口验收 step 实现（pytest-bdd 8.x）。

把 ``tests/acceptance/features/sparse_vector_recall.feature`` 中的中文 Gherkin 句子
绑定到对真实 ``VectorStorageFacade.search_sparse_chunks`` 的行为断言。所有外部依赖
（BGE-M3 / Qdrant client）都用桩件隔离，单测不接真模型 / 真服务。

state 通过 ``recall_state`` fixture 跨 step 共享。所有 step 函数都走 star-import
注册到 ``tests/acceptance/conftest.py``。

注意：pytest-bdd 8.x 的 step 函数本身**必须是同步的**——pytest 不会自动 await
async step。本模块所有 When step 用 ``asyncio.run`` 内部驱动 facade 的 async 方法。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, then, when

from src.config import settings
from src.core.qdrant_vector_storage import BucketRoute
from src.core.qdrant_vector_storage.exceptions import QdrantStoreError
from src.core.sparse_vector import (
    SparseVector,
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
# 共享 state + 桩件
# ---------------------------------------------------------------------------


@dataclass
class _RecallState:
    """每个 Scenario 一份独立状态；fixture 重建避免 Outline 互相污染。"""

    # 默认值（与 Background 对齐；Given 步骤可覆盖）
    sparse_vector_enabled: bool = True
    top_k_default: int = 10
    threshold_default: float = 0.0
    sparse_vector_name: str = "sparse_text"
    bucket_id: int = 42

    # 调用结果
    result: VectorSearchResult | None = None
    error: BaseException | None = None

    # 桩件依赖（在 fixture 里装配后回填）
    sparse_service: MagicMock | None = None
    qdrant_store: MagicMock | None = None
    facade: VectorStorageFacade | None = None
    encoder_call_count: int = 0
    qdrant_search_call_count: int = 0


@pytest.fixture
def recall_state(monkeypatch) -> _RecallState:
    """每 Scenario 一份独立桩件 + state；在 step 内动态切换 settings 等。"""
    state = _RecallState()
    # 默认对齐 Background
    monkeypatch.setattr(settings, "SPARSE_VECTOR_ENABLED", True)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_TOP_K", 10)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_SCORE_THRESHOLD", 0.0)
    monkeypatch.setattr(settings, "SPARSE_VECTOR_QDRANT_VECTOR_NAME", "sparse_text")

    # 默认 sparse vector 输出
    sparse_vector = SparseVector(indices=[1, 5, 7], values=[0.4, 0.3, 0.2])

    sparse_service = MagicMock(spec=SparseVectorService)
    sparse_service.vector_name = "sparse_text"
    sparse_service.model_name = "bge-m3-fake"

    async def _vectorize_query(query):
        state.encoder_call_count += 1
        state.last_encoded_query = query
        return sparse_vector

    sparse_service.vectorize_query = AsyncMock(side_effect=_vectorize_query)

    qdrant_store = MagicMock()
    bucket_router = MagicMock()
    bucket_router.route_user.return_value = BucketRoute(
        bucket_id=state.bucket_id, collection_name=f"kb_bucket_{state.bucket_id}",
    )
    qdrant_store.bucket_router = bucket_router

    async def _search(*, bucket_id, query_vector_spec, payload_filter, limit, score_threshold):
        state.qdrant_search_call_count += 1
        state.last_search_kwargs = {
            "bucket_id": bucket_id,
            "query_vector_spec": query_vector_spec,
            "payload_filter": payload_filter,
            "limit": limit,
            "score_threshold": score_threshold,
        }
        return list(state.fake_hits)

    qdrant_store._search_chunks = AsyncMock(side_effect=_search)
    qdrant_store.upsert_points = AsyncMock(side_effect=AssertionError("upsert_points must not be called"))
    qdrant_store.update_vectors = AsyncMock(side_effect=AssertionError("update_vectors must not be called"))
    qdrant_store.delete_points = AsyncMock(side_effect=AssertionError("delete_points must not be called"))
    qdrant_store.close = AsyncMock()

    state.fake_hits = [
        VectorSearchHit(chunk_id="c1", doc_id=10, set_id=10003, score=0.9, vector_kind="sparse"),
        VectorSearchHit(chunk_id="c2", doc_id=11, set_id=10003, score=0.5, vector_kind="sparse"),
    ]

    state.sparse_service = sparse_service
    state.qdrant_store = qdrant_store

    facade = VectorStorageFacade(
        storage_service=AsyncMock(),
        management_service=AsyncMock(),
        compensation_service=AsyncMock(),
        qdrant_store=qdrant_store,
        sparse_vector_service=sparse_service,
    )
    state.facade = facade
    return state


# ---------------------------------------------------------------------------
# Background steps
# ---------------------------------------------------------------------------


@given("配置 SPARSE_VECTOR_ENABLED=True")
def _given_sparse_enabled(recall_state: _RecallState, monkeypatch):
    monkeypatch.setattr(settings, "SPARSE_VECTOR_ENABLED", True)
    recall_state.sparse_vector_enabled = True


@given("配置 SPARSE_VECTOR_ENABLED=False")
def _given_sparse_disabled(recall_state: _RecallState, monkeypatch):
    monkeypatch.setattr(settings, "SPARSE_VECTOR_ENABLED", False)
    recall_state.sparse_vector_enabled = False


@given(parsers.parse("配置 SPARSE_RETRIEVAL_TOP_K={value:d}"))
def _given_default_top_k(recall_state: _RecallState, monkeypatch, value: int):
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_TOP_K", value)
    recall_state.top_k_default = value


@given(parsers.parse("配置 SPARSE_RETRIEVAL_SCORE_THRESHOLD={value:f}"))
def _given_default_threshold(recall_state: _RecallState, monkeypatch, value: float):
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_SCORE_THRESHOLD", value)
    recall_state.threshold_default = value


@given(parsers.parse('写入链路使用 vector name "{name}" 写入 sparse vector'))
def _given_write_vector_name(recall_state: _RecallState, name: str):
    # 写入侧 vector_name 在工厂里就是从 settings 读取的；这里仅断言两侧同源
    assert recall_state.sparse_service.vector_name == name


@given("BGE-M3 稀疏向量编码器可用")
def _given_encoder_available():
    # encoder 桩件已在 fixture 中挂好
    return None


# ---------------------------------------------------------------------------
# Scenario-specific Given
# ---------------------------------------------------------------------------


@given(parsers.parse("Qdrant 中 user_id={uid:d} 的 bucket collection 存在 {n:d} 个 sparse_text 向量"))
def _given_qdrant_has_n_vectors(recall_state: _RecallState, uid: int, n: int):
    recall_state.fake_hits = [
        VectorSearchHit(
            chunk_id=f"c{i}", doc_id=10 + i, set_id=10003,
            score=round(1.0 - i * 0.1, 2), vector_kind="sparse",
        )
        for i in range(n)
    ]


@given(parsers.parse("写入链路对 user_id {uid:d} 计算得到 bucket_id {bid:d}"))
def _given_bucket_id(recall_state: _RecallState, uid: int, bid: int):
    recall_state.bucket_id = bid
    recall_state.qdrant_store.bucket_router.route_user.return_value = BucketRoute(
        bucket_id=bid, collection_name=f"kb_bucket_{bid}",
    )


@given(parsers.parse(
    "Qdrant 接收到 score_threshold 为 {threshold:f} 时仅返回 score 不低于 {threshold2:f} 的命中"
))
def _given_threshold_filtered_hits(recall_state: _RecallState, threshold: float, threshold2: float):
    # 模拟 Qdrant 端按 score_threshold 过滤后的结果
    recall_state.fake_hits = [
        VectorSearchHit(chunk_id="c1", doc_id=10, set_id=10003, score=0.45, vector_kind="sparse"),
        VectorSearchHit(chunk_id="c2", doc_id=11, set_id=10003, score=0.31, vector_kind="sparse"),
    ]


@given(parsers.parse("Qdrant 端在 limit={limit:d} 时返回 {n:d} 条按 score 降序的命中"))
def _given_truncated_hits(recall_state: _RecallState, limit: int, n: int):
    recall_state.fake_hits = [
        VectorSearchHit(
            chunk_id=f"c{i}", doc_id=10 + i, set_id=10003,
            score=round(1.0 - i * 0.05, 2), vector_kind="sparse",
        )
        for i in range(n)
    ]


@given(parsers.parse("Qdrant 中 user_id {uid:d} 路由到的 bucket collection 不存在"))
def _given_collection_missing(recall_state: _RecallState, uid: int):
    # 让 store._search_chunks 直接返空 list（store 单测已断言 collection_exists 短路逻辑）
    async def _empty(**kwargs):
        recall_state.qdrant_search_call_count += 1
        recall_state.last_search_kwargs = kwargs
        return []
    recall_state.qdrant_store._search_chunks = AsyncMock(side_effect=_empty)


@given(parsers.parse("Qdrant 中 user_id {uid:d} 路由到的 bucket collection 存在"))
def _given_collection_exists(recall_state: _RecallState, uid: int):
    return None  # 默认就是 exists；下个 step 决定 named vector 缺失


@given(parsers.parse('该 collection 未配置 named sparse vector "{name}"'))
def _given_named_vector_missing(recall_state: _RecallState, name: str):
    async def _empty(**kwargs):
        recall_state.qdrant_search_call_count += 1
        recall_state.last_search_kwargs = kwargs
        return []
    recall_state.qdrant_store._search_chunks = AsyncMock(side_effect=_empty)


@given("稀疏向量编码器对任意输入抛底层编码异常")
def _given_encoder_raises(recall_state: _RecallState):
    recall_state.sparse_service.vectorize_query = AsyncMock(
        side_effect=SparseVectorEncodingError("bge-m3 down")
    )


@given("Qdrant 客户端对搜索请求抛底层网络异常")
def _given_qdrant_network_error(recall_state: _RecallState):
    recall_state.qdrant_store._search_chunks = AsyncMock(
        side_effect=QdrantStoreError("connection reset by peer")
    )


@given(parsers.parse("Qdrant 中 user_id={uid:d} 的 chunk 状态为已 INDEXED"))
def _given_chunks_indexed(recall_state: _RecallState, uid: int):
    return None  # fake_hits 已经按 INDEXED 状态 setup


# ---------------------------------------------------------------------------
# When：调 facade
# ---------------------------------------------------------------------------


def _resolve_blank_query(token: str) -> str:
    """把 Gherkin Examples 的字面 token 解码成实际空白字符串。"""
    return {
        "EMPTY": "",
        "SPACES": "   ",
        "TAB": "\t",
        "NEWLINE": "\n",
        "MIXED_WS": " \t \n ",
    }[token]


def _resolve_optional_int(raw: str) -> int | None:
    return None if raw == "NONE" else int(raw)


def _resolve_optional_float(raw: str) -> float | None:
    return None if raw == "NONE" else float(raw)


async def _invoke(recall_state: _RecallState, **kwargs):
    """统一调用入口：捕获返回值或异常到 state。"""
    try:
        recall_state.result = await recall_state.facade.search_sparse_chunks(**kwargs)
    except BaseException as exc:  # 捕获 ValueError / VectorRetrievalError 族
        recall_state.error = exc


def _run_invoke(recall_state: _RecallState, **kwargs) -> None:
    """同步 step 入口：包一层 asyncio.run 驱动 async facade。"""
    asyncio.run(_invoke(recall_state, **kwargs))


@when(parsers.parse(
    '调用 search_sparse_chunks 传入 query "{query}" user_id {uid:d} set_id {sid:d}'
))
def _when_call_basic(recall_state: _RecallState, query: str, uid: int, sid: int):
    _run_invoke(recall_state, query=query, user_id=uid, set_id=sid)


@when(parsers.parse(
    '调用 search_sparse_chunks 传入 query "{query}" user_id {uid:d} set_id {sid:d} top_k {k:d}'
))
def _when_call_with_top_k(recall_state: _RecallState, query: str, uid: int, sid: int, k: int):
    _run_invoke(recall_state, query=query, user_id=uid, set_id=sid, top_k=k)


@when(parsers.parse(
    '调用 search_sparse_chunks 传入 query "{query}" user_id {uid:d} set_id {sid:d} score_threshold {st:f}'
))
def _when_call_with_threshold(recall_state: _RecallState, query: str, uid: int, sid: int, st: float):
    _run_invoke(recall_state, query=query, user_id=uid, set_id=sid, score_threshold=st)


@when(parsers.parse(
    '调用 search_sparse_chunks 传入 query "{query}" user_id {uid:d} set_id {sid:d} top_k {k:d} score_threshold {st:f}'
))
def _when_call_with_top_k_and_threshold(
    recall_state: _RecallState, query: str, uid: int, sid: int, k: int, st: float,
):
    _run_invoke(recall_state, query=query, user_id=uid, set_id=sid, top_k=k, score_threshold=st)


@when(parsers.parse(
    '调用 search_sparse_chunks 传入 query "{query}" user_id {uid:d} set_id {sid:d} 不传 doc_id'
))
def _when_call_no_doc_id(recall_state: _RecallState, query: str, uid: int, sid: int):
    _run_invoke(recall_state, query=query, user_id=uid, set_id=sid, doc_id=None)


@when(parsers.parse(
    '调用 search_sparse_chunks 传入 query "{query}" user_id {uid:d} set_id {sid:d} doc_id 空列表'
))
def _when_call_empty_doc_id(recall_state: _RecallState, query: str, uid: int, sid: int):
    _run_invoke(recall_state, query=query, user_id=uid, set_id=sid, doc_id=[])


@when(parsers.parse(
    '调用 search_sparse_chunks 传入 query "{query}" user_id {uid:d} set_id {sid:d} doc_id 列表 "{ids}"'
))
def _when_call_with_doc_ids(
    recall_state: _RecallState, query: str, uid: int, sid: int, ids: str,
):
    doc_id = [int(x.strip()) for x in ids.split(",") if x.strip()]
    _run_invoke(recall_state, query=query, user_id=uid, set_id=sid, doc_id=doc_id)


@when(parsers.parse(
    '调用 search_sparse_chunks 传入 空白 query 标识 "{token}" user_id {uid:d} set_id {sid:d}'
))
def _when_call_blank_query(recall_state: _RecallState, token: str, uid: int, sid: int):
    _run_invoke(recall_state, query=_resolve_blank_query(token), user_id=uid, set_id=sid)


@when(parsers.parse(
    '调用 search_sparse_chunks 传入越界参数 user_id {uid} set_id {sid} top_k {k} score_threshold {st}'
))
def _when_call_out_of_range(
    recall_state: _RecallState, uid: str, sid: str, k: str, st: str,
):
    kwargs: dict[str, Any] = {
        "query": "q",
        "user_id": int(uid),
        "set_id": int(sid),
    }
    top_k = _resolve_optional_int(k)
    if top_k is not None:
        kwargs["top_k"] = top_k
    score_threshold = _resolve_optional_float(st)
    if score_threshold is not None:
        kwargs["score_threshold"] = score_threshold
    _run_invoke(recall_state, **kwargs)


@when(parsers.parse(
    '连续调用 search_sparse_chunks 两次 query "{query}" user_id {uid:d} set_id {sid:d}'
))
def _when_call_twice(recall_state: _RecallState, query: str, uid: int, sid: int):
    async def _twice():
        recall_state.result_first = await recall_state.facade.search_sparse_chunks(
            query=query, user_id=uid, set_id=sid,
        )
        recall_state.result_second = await recall_state.facade.search_sparse_chunks(
            query=query, user_id=uid, set_id=sid,
        )
    asyncio.run(_twice())


# ---------------------------------------------------------------------------
# Then：断言
# ---------------------------------------------------------------------------


@then(parsers.parse("返回 VectorSearchResult 长度不超过 {n:d}"))
def _then_result_len_le(recall_state: _RecallState, n: int):
    assert recall_state.error is None, f"unexpected error: {recall_state.error!r}"
    assert recall_state.result is not None
    assert len(recall_state.result.hits) <= n


@then(parsers.parse("返回 VectorSearchResult.hits 长度等于 {n:d}"))
def _then_hits_len_eq(recall_state: _RecallState, n: int):
    assert recall_state.error is None, f"unexpected error: {recall_state.error!r}"
    assert recall_state.result is not None
    assert len(recall_state.result.hits) == n


@then(parsers.re(r"hits 中每个 hit 必须含字段 (?P<fields>.+)$"))
def _then_hits_have_fields(recall_state: _RecallState, fields: str):
    expected = {f.strip() for f in fields.split(",") if f.strip()}
    actual_fields = set(VectorSearchHit.__dataclass_fields__.keys())
    assert expected <= actual_fields


@then(parsers.parse("hits 中每个 hit 不含字段 {field}"))
def _then_hits_lack_field(field: str):
    actual_fields = set(VectorSearchHit.__dataclass_fields__.keys())
    assert field not in actual_fields


@then(parsers.parse('hits 中每个 hit 的 vector_kind 等于 "{kind}"'))
def _then_each_hit_kind(recall_state: _RecallState, kind: str):
    assert all(h.vector_kind == kind for h in recall_state.result.hits)


@then("hits 按 score 降序排列")
def _then_hits_sorted(recall_state: _RecallState):
    scores = [h.score for h in recall_state.result.hits]
    assert scores == sorted(scores, reverse=True)


@then(parsers.parse('调用稀疏向量编码器一次，输入文本等于 "{text}"'))
def _then_encoder_called_with(recall_state: _RecallState, text: str):
    assert recall_state.encoder_call_count == 1
    recall_state.sparse_service.vectorize_query.assert_awaited_once_with(text)


@then("调用稀疏向量编码器一次")
def _then_encoder_called_once(recall_state: _RecallState):
    assert recall_state.encoder_call_count == 1


@then(parsers.parse('写入与查询使用相同的 vector name "{name}"'))
def _then_same_vector_name(recall_state: _RecallState, name: str):
    assert recall_state.result.vector_name == name
    assert recall_state.sparse_service.vector_name == name


@then(parsers.parse("Qdrant 搜索使用 limit 等于 {n:d}"))
def _then_search_limit(recall_state: _RecallState, n: int):
    assert recall_state.last_search_kwargs["limit"] == n


@then(parsers.parse("Qdrant 搜索使用 score_threshold 等于 {v:f}"))
def _then_search_threshold(recall_state: _RecallState, v: float):
    assert recall_state.last_search_kwargs["score_threshold"] == v


@then(parsers.parse("Qdrant 搜索使用 bucket_id 等于 {bid:d}"))
def _then_search_bucket(recall_state: _RecallState, bid: int):
    assert recall_state.last_search_kwargs["bucket_id"] == bid


@then(parsers.parse('Qdrant 搜索使用 named sparse vector "{name}"'))
def _then_search_using(recall_state: _RecallState, name: str):
    assert recall_state.last_search_kwargs["query_vector_spec"].vector_name == name


@then(parsers.parse("返回 VectorSearchResult.top_k 等于 {n:d}"))
def _then_result_top_k(recall_state: _RecallState, n: int):
    assert recall_state.result.top_k == n


@then(parsers.parse("返回 VectorSearchResult.score_threshold 等于 {v:f}"))
def _then_result_threshold(recall_state: _RecallState, v: float):
    assert recall_state.result.score_threshold == v


@then(parsers.parse('返回 VectorSearchResult.vector_name 等于 "{name}"'))
def _then_result_vector_name(recall_state: _RecallState, name: str):
    assert recall_state.result.vector_name == name


@then("VectorSearchResult 不含字段 bucket_id")
def _then_result_no_bucket_id():
    assert "bucket_id" not in VectorSearchResult.__dataclass_fields__


def _filter_must_by_key(payload_filter: Any, key: str) -> Any:
    for cond in payload_filter.must:
        if cond.key == key:
            return cond
    raise AssertionError(f"FieldCondition with key={key!r} not found in must")


@then(parsers.parse("Qdrant 搜索的 payload filter must 条件包含 user_id 等于 {value:d}"))
def _then_filter_user_id(recall_state: _RecallState, value: int):
    payload_filter = recall_state.last_search_kwargs["payload_filter"]
    cond = _filter_must_by_key(payload_filter, "user_id")
    assert cond.match.value == value


@then(parsers.parse("Qdrant 搜索的 payload filter must 条件包含 set_id 等于 {value:d}"))
def _then_filter_set_id(recall_state: _RecallState, value: int):
    payload_filter = recall_state.last_search_kwargs["payload_filter"]
    cond = _filter_must_by_key(payload_filter, "set_id")
    assert cond.match.value == value


@then("Qdrant 搜索的 payload filter 不含 doc_id 条件")
def _then_filter_no_doc_id(recall_state: _RecallState):
    payload_filter = recall_state.last_search_kwargs["payload_filter"]
    keys = [c.key for c in payload_filter.must]
    assert "doc_id" not in keys


@then(parsers.parse('Qdrant 搜索的 payload filter doc_id MatchAny 等于 "{ids}"'))
def _then_filter_doc_id_any(recall_state: _RecallState, ids: str):
    expected = [int(x.strip()) for x in ids.split(",") if x.strip()]
    payload_filter = recall_state.last_search_kwargs["payload_filter"]
    cond = _filter_must_by_key(payload_filter, "doc_id")
    assert list(cond.match.any) == expected


@then("返回的 hits 全部满足 score 不低于 0.3")
def _then_all_above_threshold(recall_state: _RecallState):
    assert all(h.score >= 0.3 for h in recall_state.result.hits)


@then("返回 VectorSearchResult.hits 为空")
def _then_hits_empty(recall_state: _RecallState):
    assert recall_state.error is None, f"unexpected error: {recall_state.error!r}"
    assert recall_state.result is not None
    assert recall_state.result.hits == []


@then("不调用稀疏向量编码器")
def _then_encoder_not_called(recall_state: _RecallState):
    assert recall_state.encoder_call_count == 0


@then("不调用 Qdrant 客户端")
def _then_qdrant_not_called(recall_state: _RecallState):
    assert recall_state.qdrant_search_call_count == 0


@then("抛出 ValueError")
def _then_value_error(recall_state: _RecallState):
    assert isinstance(recall_state.error, ValueError), f"got {recall_state.error!r}"


@then("抛出 VectorRetrievalConfigurationError")
def _then_config_error(recall_state: _RecallState):
    assert isinstance(recall_state.error, VectorRetrievalConfigurationError), f"got {recall_state.error!r}"


@then("抛出 VectorRetrievalEncodingError")
def _then_encoding_error(recall_state: _RecallState):
    assert isinstance(recall_state.error, VectorRetrievalEncodingError), f"got {recall_state.error!r}"


@then("抛出 VectorRetrievalBackendError")
def _then_backend_error(recall_state: _RecallState):
    assert isinstance(recall_state.error, VectorRetrievalBackendError), f"got {recall_state.error!r}"


@then("不抛任何异常")
def _then_no_error(recall_state: _RecallState):
    assert recall_state.error is None, f"unexpected error: {recall_state.error!r}"


@then("两次返回 hits 中 chunk_id 集合相同")
def _then_idempotent_hits(recall_state: _RecallState):
    first = {h.chunk_id for h in recall_state.result_first.hits}
    second = {h.chunk_id for h in recall_state.result_second.hits}
    assert first == second


@then("两次调用过程中不发生 Qdrant 写操作")
def _then_no_qdrant_write(recall_state: _RecallState):
    recall_state.qdrant_store.upsert_points.assert_not_called()
    recall_state.qdrant_store.update_vectors.assert_not_called()
    recall_state.qdrant_store.delete_points.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario 22：对外暴露面
# ---------------------------------------------------------------------------


@then("从 vector_storage 包可以导入 VectorStorageFacade")
def _then_can_import_facade():
    from src.core.vector_storage import VectorStorageFacade as F  # noqa: F401


@then("从 vector_storage 包可以导入 VectorSearchHit, VectorSearchResult")
def _then_can_import_dataclasses():
    from src.core.vector_storage import VectorSearchHit as H, VectorSearchResult as R  # noqa: F401


@then("从 vector_storage 包可以导入召回侧异常族")
def _then_can_import_exceptions():
    from src.core.vector_storage import (  # noqa: F401
        VectorRetrievalBackendError as B,
        VectorRetrievalConfigurationError as C,
        VectorRetrievalEncodingError as E,
        VectorRetrievalError as Base,
    )


@then("SparseVectorSearchRequest 不在 vector_storage 包的 __all__ 中")
def _then_request_not_in_all():
    import src.core.vector_storage as vs
    assert "SparseVectorSearchRequest" not in vs.__all__


@then("SparseQueryVectorSpec 不在 vector_storage 包的 __all__ 中")
def _then_spec_not_in_all():
    import src.core.vector_storage as vs
    assert "SparseQueryVectorSpec" not in vs.__all__
    assert "QueryVectorSpec" not in vs.__all__


@then("VectorRetrieval 异常族继承关系正确")
def _then_exception_hierarchy():
    assert issubclass(VectorRetrievalConfigurationError, VectorRetrievalError)
    assert issubclass(VectorRetrievalBackendError, VectorRetrievalError)
    assert issubclass(VectorRetrievalEncodingError, VectorRetrievalError)
