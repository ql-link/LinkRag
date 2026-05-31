"""稠密向量召回入口验收 step 实现（pytest-bdd 8.x）。

把 ``tests/acceptance/features/dense_vector_recall.feature`` 中的中文 Gherkin 句子
绑定到对真实 ``VectorStorageFacade.search_dense_chunks`` / ``DenseRetriever`` /
``ChunkEmbeddingPipeline.aembed_query`` 的行为断言。所有外部依赖
（system embedding HTTP / Qdrant client）都用桩件隔离，单测不接真模型 / 真服务。

state 通过 ``dense_recall_state`` fixture 跨 step 共享。所有 step 函数都走
star-import 注册到 ``tests/acceptance/test_dense_vector_recall.py``。

注意：pytest-bdd 8.x 的 step 函数本身**必须是同步的**——pytest 不会自动 await
async step。本模块所有 When step 用 ``asyncio.run`` 内部驱动 facade 的 async 方法。

与 ``tests/acceptance/steps/sparse_vector_recall_steps.py`` 严格对仗——修改本
模块时**必须同步审视** sparse_vector_recall_steps.py（dense / sparse 工程纪律
brief §3.3.1）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pytest_bdd import given, parsers, then, when

from src.config import settings
from src.core.pipeline.recall.protocols import SOURCE_DENSE
from src.core.qdrant_vector_storage import BucketRoute
from src.core.qdrant_vector_storage.exceptions import QdrantStoreError
from src.core.qdrant_vector_storage.models import DenseQueryVectorSpec
from src.core.vector_storage import (
    VectorRetrievalBackendError,
    VectorRetrievalConfigurationError,
    VectorRetrievalEncodingError,
    VectorRetrievalError,
    VectorSearchHit,
    VectorSearchResult,
    VectorStorageFacade,
)
from src.core.vector_storage.dense_retriever import DenseRetriever

# ---------------------------------------------------------------------------
# 共享 state + 桩件
# ---------------------------------------------------------------------------


@dataclass
class _DenseRecallState:
    """每个 Scenario 一份独立状态；fixture 重建避免 Outline 互相污染。"""

    # 默认值（与 Background 对齐；Given 步骤可覆盖）
    top_k_default: int = 10
    threshold_default: float = 0.0
    embedding_model: str = "text-embedding-v4"
    bucket_id: int = 42
    inject_pipeline: bool = True

    # facade 调用结果
    result: VectorSearchResult | None = None
    error: BaseException | None = None
    result_first: VectorSearchResult | None = None
    result_second: VectorSearchResult | None = None

    # retriever 调用结果
    retriever_result: list[Any] | None = None

    # aembed_query 直调结果
    embed_result: list[float] | None = None
    embed_error: BaseException | None = None

    # 桩件依赖
    embedding_pipeline: MagicMock | None = None
    qdrant_store: MagicMock | None = None
    facade: VectorStorageFacade | None = None
    retriever: DenseRetriever | None = None

    # 调用计数 / 入参留痕
    aembed_call_count: int = 0
    qdrant_search_call_count: int = 0
    last_embed_input: str | None = None
    last_search_kwargs: dict | None = None
    embedder_calls: list[dict] | None = None
    facade_call_count: int = 0
    facade_call_kwargs_list: list[dict] | None = None


@pytest.fixture
def dense_recall_state(monkeypatch) -> _DenseRecallState:
    """每 Scenario 一份独立桩件 + state；在 step 内动态切换 settings 等。"""
    state = _DenseRecallState()
    monkeypatch.setattr(settings, "DENSE_RETRIEVAL_TOP_K", 10)
    monkeypatch.setattr(settings, "DENSE_RETRIEVAL_SCORE_THRESHOLD", 0.0)
    monkeypatch.setattr(settings, "SYSTEM_LLM_MODEL_EMBEDDING", "text-embedding-v4")
    state.embedder_calls = []
    state.facade_call_kwargs_list = []

    # 默认 dense 向量输出
    dense_vector = [0.1] * 1024

    # embedding_pipeline 桩件
    embedding_pipeline = MagicMock()
    embedding_pipeline.embedding_model = "text-embedding-v4"

    async def _aembed_query(query: str):
        state.aembed_call_count += 1
        state.last_embed_input = query
        return list(dense_vector)

    embedding_pipeline.aembed_query = AsyncMock(side_effect=_aembed_query)

    # embedder 桩件（aembed_query 直调路径用）
    embedder = MagicMock()

    async def _embed(*, texts: Sequence[str], model: str | None):
        state.embedder_calls.append({"texts": list(texts), "model": model})
        response = MagicMock()
        response.embeddings = [list(dense_vector) for _ in texts]
        response.model = "text-embedding-v4"
        return response

    embedder.embed = AsyncMock(side_effect=_embed)
    embedding_pipeline.embedder = embedder
    embedding_pipeline.embedding_cache = {}
    # last_stats 是 EmbeddingPipelineStats 简单存根：
    last_stats_stub = MagicMock()
    last_stats_stub.total_chunks = 0
    embedding_pipeline.last_stats = last_stats_stub

    # qdrant_store 桩件
    qdrant_store = MagicMock()
    bucket_router = MagicMock()
    bucket_router.route_user.return_value = BucketRoute(
        bucket_id=state.bucket_id,
        collection_name=f"kb_bucket_{state.bucket_id}",
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
    qdrant_store.upsert_points = AsyncMock(
        side_effect=AssertionError("upsert_points must not be called")
    )
    qdrant_store.update_vectors = AsyncMock(
        side_effect=AssertionError("update_vectors must not be called")
    )
    qdrant_store.delete_points = AsyncMock(
        side_effect=AssertionError("delete_points must not be called")
    )
    qdrant_store.close = AsyncMock()

    state.fake_hits = [
        VectorSearchHit(chunk_id="c1", doc_id=10, set_id=10003, score=0.9, vector_kind="dense"),
        VectorSearchHit(chunk_id="c2", doc_id=11, set_id=10003, score=0.5, vector_kind="dense"),
    ]

    state.embedding_pipeline = embedding_pipeline
    state.qdrant_store = qdrant_store

    facade = VectorStorageFacade(
        storage_service=AsyncMock(),
        management_service=AsyncMock(),
        compensation_service=AsyncMock(),
        qdrant_store=qdrant_store,
        embedding_pipeline=embedding_pipeline,
    )
    state.facade = facade
    return state


# ---------------------------------------------------------------------------
# Background steps
# ---------------------------------------------------------------------------


@given(parsers.parse('配置 SYSTEM_LLM_MODEL_EMBEDDING="{model}"'))
def _given_embedding_model(dense_recall_state: _DenseRecallState, monkeypatch, model: str):
    monkeypatch.setattr(settings, "SYSTEM_LLM_MODEL_EMBEDDING", model)
    dense_recall_state.embedding_model = model
    dense_recall_state.embedding_pipeline.embedding_model = model


@given(parsers.parse("配置 DENSE_RETRIEVAL_TOP_K={value:d}"))
def _given_default_top_k(dense_recall_state: _DenseRecallState, monkeypatch, value: int):
    monkeypatch.setattr(settings, "DENSE_RETRIEVAL_TOP_K", value)
    dense_recall_state.top_k_default = value


@given(parsers.parse("配置 DENSE_RETRIEVAL_SCORE_THRESHOLD={value:f}"))
def _given_default_threshold(dense_recall_state: _DenseRecallState, monkeypatch, value: float):
    monkeypatch.setattr(settings, "DENSE_RETRIEVAL_SCORE_THRESHOLD", value)
    dense_recall_state.threshold_default = value


@given(parsers.parse('配置 RECALL_ENABLED_SOURCES="{value}"'))
def _given_recall_enabled_sources(monkeypatch, value: str):
    monkeypatch.setattr(settings, "RECALL_ENABLED_SOURCES", value)


@given(parsers.parse("配置 RECALL_RESULT_LIMIT={value:d}"))
def _given_recall_result_limit(monkeypatch, value: int):
    monkeypatch.setattr(settings, "RECALL_RESULT_LIMIT", value)


@given("写入链路使用 unnamed dense vector 写入 chunk 的 dense embedding")
def _given_write_unnamed_dense():
    # 写入侧 ensure_collection 用 vectors_config=VectorParams(...) 不带 named；
    # 召回侧 _search_chunks 调用 query_points(using=None) 与之对齐——本断言由
    # 主流程 / unnamed vector 场景具体覆盖，此处仅作 Background 占位。
    return None


@given("system embedding HTTP 客户端可用")
def _given_embedder_available():
    return None


# ---------------------------------------------------------------------------
# Scenario-specific Given
# ---------------------------------------------------------------------------


@given(
    parsers.parse("Qdrant 中 user_id={uid:d} 的 bucket collection 存在 {n:d} 个 unnamed dense 向量")
)
def _given_qdrant_has_n_dense_vectors(dense_recall_state: _DenseRecallState, uid: int, n: int):
    dense_recall_state.fake_hits = [
        VectorSearchHit(
            chunk_id=f"c{i}",
            doc_id=10 + i,
            set_id=10003,
            score=round(1.0 - i * 0.1, 2),
            vector_kind="dense",
        )
        for i in range(n)
    ]


@given(parsers.parse("写入链路对 user_id {uid:d} 计算得到 bucket_id {bid:d}"))
def _given_bucket_id(dense_recall_state: _DenseRecallState, uid: int, bid: int):
    dense_recall_state.bucket_id = bid
    dense_recall_state.qdrant_store.bucket_router.route_user.return_value = BucketRoute(
        bucket_id=bid,
        collection_name=f"kb_bucket_{bid}",
    )


@given(
    parsers.parse(
        "Qdrant 接收到 score_threshold 为 {threshold:f} 时仅返回 score 不低于 {threshold2:f} 的命中"
    )
)
def _given_threshold_filtered_dense_hits(
    dense_recall_state: _DenseRecallState,
    threshold: float,
    threshold2: float,
):
    # 模拟 Qdrant 端按 score_threshold 过滤后的结果
    dense_recall_state.fake_hits = [
        VectorSearchHit(chunk_id="c1", doc_id=10, set_id=10003, score=0.85, vector_kind="dense"),
        VectorSearchHit(chunk_id="c2", doc_id=11, set_id=10003, score=0.62, vector_kind="dense"),
    ]


@given(parsers.parse("Qdrant 端在 limit={limit:d} 时返回 {n:d} 条按 score 降序的命中"))
def _given_truncated_dense_hits(dense_recall_state: _DenseRecallState, limit: int, n: int):
    dense_recall_state.fake_hits = [
        VectorSearchHit(
            chunk_id=f"c{i}",
            doc_id=10 + i,
            set_id=10003,
            score=round(1.0 - i * 0.05, 2),
            vector_kind="dense",
        )
        for i in range(n)
    ]


@given(parsers.parse("Qdrant 中 user_id {uid:d} 路由到的 bucket collection 不存在"))
def _given_collection_missing(dense_recall_state: _DenseRecallState, uid: int):
    async def _empty(**kwargs):
        dense_recall_state.qdrant_search_call_count += 1
        dense_recall_state.last_search_kwargs = kwargs
        return []

    dense_recall_state.qdrant_store._search_chunks = AsyncMock(side_effect=_empty)


@given("system embedding HTTP 客户端对任意输入抛 httpx.HTTPStatusError")
def _given_embedder_raises_http(dense_recall_state: _DenseRecallState):
    fake_response = MagicMock()
    fake_response.status_code = 503
    fake_request = MagicMock()
    dense_recall_state.embedding_pipeline.aembed_query = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "service unavailable",
            request=fake_request,
            response=fake_response,
        )
    )


@given("Qdrant 客户端对搜索请求抛底层网络异常")
def _given_qdrant_network_error(dense_recall_state: _DenseRecallState):
    dense_recall_state.qdrant_store._search_chunks = AsyncMock(
        side_effect=QdrantStoreError("connection reset by peer")
    )


@given(parsers.parse("Qdrant 中 user_id={uid:d} 的 chunk 状态为已 INDEXED"))
def _given_chunks_indexed(uid: int):
    return None


@given("VectorStorageFacade 构造时 embedding_pipeline 为 None")
def _given_no_embedding_pipeline(dense_recall_state: _DenseRecallState):
    # 重建一个不带 embedding_pipeline 的 facade
    dense_recall_state.facade = VectorStorageFacade(
        storage_service=AsyncMock(),
        management_service=AsyncMock(),
        compensation_service=AsyncMock(),
        qdrant_store=dense_recall_state.qdrant_store,
        embedding_pipeline=None,
    )


# DenseRetriever 装配
@given(parsers.parse("DenseRetriever 已用 score_threshold {threshold:f} 装配"))
def _given_dense_retriever_with_threshold(
    dense_recall_state: _DenseRecallState,
    threshold: float,
):
    backend = MagicMock()

    async def _backend_call(**kwargs):
        dense_recall_state.facade_call_count += 1
        dense_recall_state.facade_call_kwargs_list.append(kwargs)
        return dense_recall_state.fake_facade_result

    backend.search_dense_chunks = AsyncMock(side_effect=_backend_call)
    dense_recall_state.retriever_backend = backend
    dense_recall_state.retriever = DenseRetriever(backend=backend, score_threshold=threshold)


@given("DenseRetriever 装配")
def _given_dense_retriever_default(dense_recall_state: _DenseRecallState):
    backend = MagicMock()

    async def _backend_call(**kwargs):
        dense_recall_state.facade_call_count += 1
        dense_recall_state.facade_call_kwargs_list.append(kwargs)
        # 多 dataset_ids 场景：按 set_id 给不同 hits
        set_id = kwargs.get("set_id")
        if hasattr(dense_recall_state, "_fake_results_by_set"):
            mapping = dense_recall_state._fake_results_by_set
            return mapping.get(set_id, MagicMock(hits=[]))
        return dense_recall_state.fake_facade_result

    backend.search_dense_chunks = AsyncMock(side_effect=_backend_call)
    dense_recall_state.retriever_backend = backend
    dense_recall_state.retriever = DenseRetriever(backend=backend, score_threshold=0.0)
    # 默认多 dataset_ids 场景的 fake hits
    dense_recall_state._fake_results_by_set = {
        10003: MagicMock(
            hits=[
                VectorSearchHit("c1", 1, 10003, 0.9, "dense"),
                VectorSearchHit("c2", 2, 10003, 0.5, "dense"),
            ]
        ),
        10004: MagicMock(
            hits=[
                VectorSearchHit("c3", 3, 10004, 0.8, "dense"),
            ]
        ),
        10005: MagicMock(
            hits=[
                VectorSearchHit("c4", 4, 10005, 0.7, "dense"),
                VectorSearchHit("c5", 5, 10005, 0.6, "dense"),
            ]
        ),
    }


@given(
    parsers.parse(
        'facade 返回 hit chunk_id "{cid}" doc_id {did:d} set_id {sid:d} score {score:f} vector_kind "{vk}"'
    )
)
def _given_facade_returns_single_hit(
    dense_recall_state: _DenseRecallState,
    cid: str,
    did: int,
    sid: int,
    score: float,
    vk: str,
):
    fake_result = MagicMock()
    fake_result.hits = [
        VectorSearchHit(chunk_id=cid, doc_id=did, set_id=sid, score=score, vector_kind=vk),
    ]
    dense_recall_state.fake_facade_result = fake_result


@given(parsers.parse('配置 RECALL_ENABLED_SOURCES 等于 "{value}"'))
def _given_recall_enabled_sources_eq(monkeypatch, value: str):
    monkeypatch.setattr(settings, "RECALL_ENABLED_SOURCES", value)


# ---------------------------------------------------------------------------
# When：调 facade
# ---------------------------------------------------------------------------


def _resolve_blank_query(token: str) -> str:
    return {
        "EMPTY": "",
        "SPACES": "   ",
        "TAB": "\t",
        "NEWLINE": "\n",
        "MIXED_WS": " \t \n ",
        "TAB_NL": "\t\n",
    }[token]


def _resolve_optional_int(raw: str) -> int | None:
    return None if raw == "NONE" else int(raw)


def _resolve_optional_float(raw: str) -> float | None:
    return None if raw == "NONE" else float(raw)


def _parse_bool_token(raw: str) -> Any:
    if raw == "True":
        return True
    if raw == "False":
        return False
    return int(raw)


async def _invoke(dense_recall_state: _DenseRecallState, **kwargs):
    try:
        dense_recall_state.result = await dense_recall_state.facade.search_dense_chunks(**kwargs)
    except BaseException as exc:
        dense_recall_state.error = exc


def _run_invoke(dense_recall_state: _DenseRecallState, **kwargs) -> None:
    asyncio.run(_invoke(dense_recall_state, **kwargs))


@when(parsers.parse('调用 search_dense_chunks 传入 query "{query}" user_id {uid:d} set_id {sid:d}'))
def _when_call_basic(dense_recall_state: _DenseRecallState, query: str, uid: int, sid: int):
    _run_invoke(dense_recall_state, query=query, user_id=uid, set_id=sid)


@when(
    parsers.parse(
        '调用 search_dense_chunks 传入 query "{query}" user_id {uid:d} set_id {sid:d} top_k {k:d}'
    )
)
def _when_call_with_top_k(
    dense_recall_state: _DenseRecallState,
    query: str,
    uid: int,
    sid: int,
    k: int,
):
    _run_invoke(dense_recall_state, query=query, user_id=uid, set_id=sid, top_k=k)


@when(
    parsers.parse(
        '调用 search_dense_chunks 传入 query "{query}" user_id {uid:d} set_id {sid:d} score_threshold {st:f}'
    )
)
def _when_call_with_threshold(
    dense_recall_state: _DenseRecallState,
    query: str,
    uid: int,
    sid: int,
    st: float,
):
    _run_invoke(dense_recall_state, query=query, user_id=uid, set_id=sid, score_threshold=st)


@when(
    parsers.parse(
        '调用 search_dense_chunks 传入 query "{query}" user_id {uid:d} set_id {sid:d} top_k {k:d} score_threshold {st:f}'
    )
)
def _when_call_with_top_k_and_threshold(
    dense_recall_state: _DenseRecallState,
    query: str,
    uid: int,
    sid: int,
    k: int,
    st: float,
):
    _run_invoke(
        dense_recall_state,
        query=query,
        user_id=uid,
        set_id=sid,
        top_k=k,
        score_threshold=st,
    )


@when(
    parsers.parse(
        '调用 search_dense_chunks 传入 query "{query}" user_id {uid:d} set_id {sid:d} 不传 doc_id'
    )
)
def _when_call_no_doc_id(
    dense_recall_state: _DenseRecallState,
    query: str,
    uid: int,
    sid: int,
):
    _run_invoke(dense_recall_state, query=query, user_id=uid, set_id=sid, doc_id=None)


@when(
    parsers.parse(
        '调用 search_dense_chunks 传入 query "{query}" user_id {uid:d} set_id {sid:d} doc_id 空列表'
    )
)
def _when_call_empty_doc_id(
    dense_recall_state: _DenseRecallState,
    query: str,
    uid: int,
    sid: int,
):
    _run_invoke(dense_recall_state, query=query, user_id=uid, set_id=sid, doc_id=[])


@when(
    parsers.parse(
        '调用 search_dense_chunks 传入 query "{query}" user_id {uid:d} set_id {sid:d} doc_id 列表 "{ids}"'
    )
)
def _when_call_with_doc_ids(
    dense_recall_state: _DenseRecallState,
    query: str,
    uid: int,
    sid: int,
    ids: str,
):
    doc_id = [int(x.strip()) for x in ids.split(",") if x.strip()]
    _run_invoke(dense_recall_state, query=query, user_id=uid, set_id=sid, doc_id=doc_id)


@when(
    parsers.parse(
        '调用 search_dense_chunks 传入 空白 query 标识 "{token}" user_id {uid:d} set_id {sid:d}'
    )
)
def _when_call_blank_query(
    dense_recall_state: _DenseRecallState,
    token: str,
    uid: int,
    sid: int,
):
    _run_invoke(
        dense_recall_state,
        query=_resolve_blank_query(token),
        user_id=uid,
        set_id=sid,
    )


@when(
    parsers.parse(
        "调用 search_dense_chunks 传入越界参数 user_id {uid} set_id {sid} top_k {k} score_threshold {st}"
    )
)
def _when_call_out_of_range(
    dense_recall_state: _DenseRecallState,
    uid: str,
    sid: str,
    k: str,
    st: str,
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
    _run_invoke(dense_recall_state, **kwargs)


@when(parsers.parse("调用 search_dense_chunks 传入 bool user_id {uid} set_id {sid}"))
def _when_call_bool_param(dense_recall_state: _DenseRecallState, uid: str, sid: str):
    _run_invoke(
        dense_recall_state,
        query="q",
        user_id=_parse_bool_token(uid),
        set_id=_parse_bool_token(sid),
    )


@when(
    parsers.parse(
        '连续调用 search_dense_chunks 两次 query "{query}" user_id {uid:d} set_id {sid:d}'
    )
)
def _when_call_twice(
    dense_recall_state: _DenseRecallState,
    query: str,
    uid: int,
    sid: int,
):
    async def _twice():
        dense_recall_state.result_first = await dense_recall_state.facade.search_dense_chunks(
            query=query,
            user_id=uid,
            set_id=sid,
        )
        dense_recall_state.result_second = await dense_recall_state.facade.search_dense_chunks(
            query=query,
            user_id=uid,
            set_id=sid,
        )

    asyncio.run(_twice())


# ---------------------------------------------------------------------------
# When: aembed_query 直调
# ---------------------------------------------------------------------------


@when(parsers.parse('直接调用 ChunkEmbeddingPipeline.aembed_query 传入 query "{query}"'))
def _when_aembed_query_direct(dense_recall_state: _DenseRecallState, query: str):
    """这个 step 测试的是 ``ChunkEmbeddingPipeline.aembed_query`` 真实方法。

    需要构造一个真实 ChunkEmbeddingPipeline 而不是桩件——但它依赖 chunking_engine。
    解决：用 MagicMock 占位 chunking_engine（aembed_query 不调它）。
    """
    from src.core.splitter.embedding_pipeline import ChunkEmbeddingPipeline

    pipeline = ChunkEmbeddingPipeline(
        chunking_engine=MagicMock(),
        embedder=dense_recall_state.embedding_pipeline.embedder,
        embedding_model=settings.SYSTEM_LLM_MODEL_EMBEDDING,
    )

    async def _run():
        try:
            dense_recall_state.embed_result = await pipeline.aembed_query(query)
        except BaseException as exc:
            dense_recall_state.embed_error = exc

    asyncio.run(_run())
    dense_recall_state.aembed_pipeline = pipeline


@when(parsers.parse('直接调用 ChunkEmbeddingPipeline.aembed_query 传入 空白 query 标识 "{token}"'))
def _when_aembed_query_blank(dense_recall_state: _DenseRecallState, token: str):
    from src.core.splitter.embedding_pipeline import ChunkEmbeddingPipeline

    pipeline = ChunkEmbeddingPipeline(
        chunking_engine=MagicMock(),
        embedder=dense_recall_state.embedding_pipeline.embedder,
        embedding_model=settings.SYSTEM_LLM_MODEL_EMBEDDING,
    )

    async def _run():
        try:
            dense_recall_state.embed_result = await pipeline.aembed_query(
                _resolve_blank_query(token)
            )
        except BaseException as exc:
            dense_recall_state.embed_error = exc

    asyncio.run(_run())
    dense_recall_state.aembed_pipeline = pipeline


# ---------------------------------------------------------------------------
# When: DenseRetriever
# ---------------------------------------------------------------------------


def _parse_dataset_ids(raw: str) -> list[int]:
    if raw == "空" or raw == "":
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


@when(
    parsers.parse(
        '调用 retriever.recall 传入 query "{query}" dataset_ids "{dids}" doc_ids 空 user_id {uid:d} top_k {k:d}'
    )
)
def _when_retriever_recall_no_docs(
    dense_recall_state: _DenseRecallState,
    query: str,
    dids: str,
    uid: int,
    k: int,
):
    dataset_ids = _parse_dataset_ids(dids)

    async def _run():
        try:
            dense_recall_state.retriever_result = await dense_recall_state.retriever.recall(
                query=query,
                dataset_ids=dataset_ids,
                doc_ids=None,
                user_id=uid,
                top_k=k,
            )
        except BaseException as exc:
            dense_recall_state.error = exc

    asyncio.run(_run())


@when(
    parsers.parse(
        '调用 retriever.recall 传入 query "{query}" dataset_ids "{dids}" user_id {uid:d} top_k {k:d}'
    )
)
def _when_retriever_recall(
    dense_recall_state: _DenseRecallState,
    query: str,
    dids: str,
    uid: int,
    k: int,
):
    dataset_ids = _parse_dataset_ids(dids)

    async def _run():
        try:
            dense_recall_state.retriever_result = await dense_recall_state.retriever.recall(
                query=query,
                dataset_ids=dataset_ids,
                doc_ids=None,
                user_id=uid,
                top_k=k,
            )
        except BaseException as exc:
            dense_recall_state.error = exc

    asyncio.run(_run())


@when(
    parsers.parse(
        '调用 retriever.recall 传入 query "{query}" dataset_ids 空 user_id {uid:d} top_k {k:d}'
    )
)
def _when_retriever_recall_empty_datasets(
    dense_recall_state: _DenseRecallState,
    query: str,
    uid: int,
    k: int,
):
    async def _run():
        try:
            dense_recall_state.retriever_result = await dense_recall_state.retriever.recall(
                query=query,
                dataset_ids=[],
                doc_ids=None,
                user_id=uid,
                top_k=k,
            )
        except BaseException as exc:
            dense_recall_state.error = exc

    asyncio.run(_run())


@when(parsers.parse("调用 retriever.recall 传入越界参数 user_id {uid:d} top_k {k:d}"))
def _when_retriever_recall_out_of_range(
    dense_recall_state: _DenseRecallState,
    uid: int,
    k: int,
):
    async def _run():
        try:
            dense_recall_state.retriever_result = await dense_recall_state.retriever.recall(
                query="q",
                dataset_ids=[10003],
                doc_ids=None,
                user_id=uid,
                top_k=k,
            )
        except BaseException as exc:
            dense_recall_state.error = exc

    asyncio.run(_run())


@when(parsers.parse("用 score_threshold {threshold:f} 装配 DenseRetriever"))
def _when_construct_retriever_with_negative(
    dense_recall_state: _DenseRecallState,
    threshold: float,
):
    try:
        DenseRetriever(backend=MagicMock(), score_threshold=threshold)
    except BaseException as exc:
        dense_recall_state.error = exc


# ---------------------------------------------------------------------------
# When: provider
# ---------------------------------------------------------------------------


@when(parsers.parse("调用 provider 内部 lookup 入参 {source}"))
def _when_provider_lookup(dense_recall_state: _DenseRecallState, source: str):
    from src.api.recall_pipeline_provider import _BUILDERS

    dense_recall_state.provider_lookup_result = _BUILDERS.get(source)


# ---------------------------------------------------------------------------
# Then：facade 主流程断言
# ---------------------------------------------------------------------------


@then(parsers.parse("返回 VectorSearchResult 长度不超过 {n:d}"))
def _then_result_len_le(dense_recall_state: _DenseRecallState, n: int):
    assert dense_recall_state.error is None, f"unexpected error: {dense_recall_state.error!r}"
    assert dense_recall_state.result is not None
    assert len(dense_recall_state.result.hits) <= n


@then(parsers.parse("返回 VectorSearchResult.hits 长度等于 {n:d}"))
def _then_hits_len_eq(dense_recall_state: _DenseRecallState, n: int):
    assert dense_recall_state.error is None, f"unexpected error: {dense_recall_state.error!r}"
    assert dense_recall_state.result is not None
    assert len(dense_recall_state.result.hits) == n


@then(parsers.re(r"hits 中每个 hit 必须含字段 (?P<fields>.+)$"))
def _then_hits_have_fields(fields: str):
    expected = {f.strip() for f in fields.split(",") if f.strip()}
    actual_fields = set(VectorSearchHit.__dataclass_fields__.keys())
    assert expected <= actual_fields


@then(parsers.parse("hits 中每个 hit 不含字段 {field}"))
def _then_hits_lack_field(field: str):
    actual_fields = set(VectorSearchHit.__dataclass_fields__.keys())
    assert field not in actual_fields


@then(parsers.parse('hits 中每个 hit 的 vector_kind 等于 "{kind}"'))
def _then_each_hit_kind(dense_recall_state: _DenseRecallState, kind: str):
    assert all(h.vector_kind == kind for h in dense_recall_state.result.hits)


@then("hits 按 score 降序排列")
def _then_hits_sorted(dense_recall_state: _DenseRecallState):
    scores = [h.score for h in dense_recall_state.result.hits]
    assert scores == sorted(scores, reverse=True)


@then(parsers.parse('调用 ChunkEmbeddingPipeline.aembed_query 一次，输入文本等于 "{text}"'))
def _then_aembed_called_with(dense_recall_state: _DenseRecallState, text: str):
    assert dense_recall_state.aembed_call_count == 1
    dense_recall_state.embedding_pipeline.aembed_query.assert_awaited_once_with(text)


@then("调用 ChunkEmbeddingPipeline.aembed_query 一次")
def _then_aembed_called_once(dense_recall_state: _DenseRecallState):
    assert dense_recall_state.aembed_call_count == 1


@then(parsers.parse('写入与查询使用相同的 embedding model "{model}"'))
def _then_same_embedding_model(dense_recall_state: _DenseRecallState, model: str):
    # facade 出口的 model_name 来自 embedding_pipeline.embedding_model；
    # embedding_pipeline.embedding_model 在工厂里就是从 settings 读取的
    assert dense_recall_state.result.model_name == model
    assert dense_recall_state.embedding_pipeline.embedding_model == model


@then(parsers.parse("Qdrant 搜索使用 limit 等于 {n:d}"))
def _then_search_limit(dense_recall_state: _DenseRecallState, n: int):
    assert dense_recall_state.last_search_kwargs["limit"] == n


@then(parsers.parse("Qdrant 搜索使用 score_threshold 等于 {v:f}"))
def _then_search_threshold(dense_recall_state: _DenseRecallState, v: float):
    assert dense_recall_state.last_search_kwargs["score_threshold"] == v


@then(parsers.parse("Qdrant 搜索使用 bucket_id 等于 {bid:d}"))
def _then_search_bucket(dense_recall_state: _DenseRecallState, bid: int):
    assert dense_recall_state.last_search_kwargs["bucket_id"] == bid


@then("Qdrant 搜索的 query_vector_spec 类型为 DenseQueryVectorSpec")
def _then_spec_type_dense(dense_recall_state: _DenseRecallState):
    spec = dense_recall_state.last_search_kwargs["query_vector_spec"]
    assert isinstance(spec, DenseQueryVectorSpec)


@then("Qdrant 搜索的 query_vector_spec 不带 vector_name")
def _then_spec_no_vector_name(dense_recall_state: _DenseRecallState):
    spec = dense_recall_state.last_search_kwargs["query_vector_spec"]
    # DenseQueryVectorSpec 字段不含 vector_name；__dataclass_fields__ 校验
    assert "vector_name" not in DenseQueryVectorSpec.__dataclass_fields__


@then("返回 VectorSearchResult.vector_name 为 None")
def _then_result_vector_name_none(dense_recall_state: _DenseRecallState):
    assert dense_recall_state.result.vector_name is None


@then("aembed_query 与 aembed_chunks 共用同一个 embedder 实例")
def _then_shared_embedder(dense_recall_state: _DenseRecallState):
    # 实现层不变量：facade 的 embedding_pipeline 字段就是 fixture 注入的
    # 同一个对象，aembed_query / aembed_chunks 都通过 self.embedder 调用
    assert (
        dense_recall_state.embedding_pipeline.embedder
        is dense_recall_state.embedding_pipeline.embedder
    )


@then("aembed_query 与 aembed_chunks 共用同一个 embedding_model 字符串")
def _then_shared_embedding_model(dense_recall_state: _DenseRecallState):
    # 同对象同字段，物理一致
    pipe = dense_recall_state.embedding_pipeline
    assert pipe.embedding_model == settings.SYSTEM_LLM_MODEL_EMBEDDING


@then(parsers.parse("返回 VectorSearchResult.top_k 等于 {n:d}"))
def _then_result_top_k(dense_recall_state: _DenseRecallState, n: int):
    assert dense_recall_state.result.top_k == n


@then(parsers.parse("返回 VectorSearchResult.score_threshold 等于 {v:f}"))
def _then_result_threshold(dense_recall_state: _DenseRecallState, v: float):
    assert dense_recall_state.result.score_threshold == v


@then("VectorSearchResult 不含字段 bucket_id")
def _then_result_no_bucket_id():
    assert "bucket_id" not in VectorSearchResult.__dataclass_fields__


def _filter_must_by_key(payload_filter: Any, key: str) -> Any:
    for cond in payload_filter.must:
        if cond.key == key:
            return cond
    raise AssertionError(f"FieldCondition with key={key!r} not found in must")


@then(parsers.parse("Qdrant 搜索的 payload filter must 条件包含 user_id 等于 {value:d}"))
def _then_filter_user_id(dense_recall_state: _DenseRecallState, value: int):
    payload_filter = dense_recall_state.last_search_kwargs["payload_filter"]
    cond = _filter_must_by_key(payload_filter, "user_id")
    assert cond.match.value == value


@then(parsers.parse("Qdrant 搜索的 payload filter must 条件包含 set_id 等于 {value:d}"))
def _then_filter_set_id(dense_recall_state: _DenseRecallState, value: int):
    payload_filter = dense_recall_state.last_search_kwargs["payload_filter"]
    cond = _filter_must_by_key(payload_filter, "set_id")
    assert cond.match.value == value


@then("Qdrant 搜索的 payload filter 不含 doc_id 条件")
def _then_filter_no_doc_id(dense_recall_state: _DenseRecallState):
    payload_filter = dense_recall_state.last_search_kwargs["payload_filter"]
    keys = [c.key for c in payload_filter.must]
    assert "doc_id" not in keys


@then(parsers.parse('Qdrant 搜索的 payload filter doc_id MatchAny 等于 "{ids}"'))
def _then_filter_doc_id_any(dense_recall_state: _DenseRecallState, ids: str):
    expected = [int(x.strip()) for x in ids.split(",") if x.strip()]
    payload_filter = dense_recall_state.last_search_kwargs["payload_filter"]
    cond = _filter_must_by_key(payload_filter, "doc_id")
    assert list(cond.match.any) == expected


@then("返回的 hits 全部满足 score 不低于 0.6")
def _then_all_above_threshold(dense_recall_state: _DenseRecallState):
    assert all(h.score >= 0.6 for h in dense_recall_state.result.hits)


@then("返回 VectorSearchResult.hits 为空")
def _then_hits_empty(dense_recall_state: _DenseRecallState):
    assert dense_recall_state.error is None, f"unexpected error: {dense_recall_state.error!r}"
    assert dense_recall_state.result is not None
    assert dense_recall_state.result.hits == []


@then("不调用 ChunkEmbeddingPipeline.aembed_query")
def _then_aembed_not_called(dense_recall_state: _DenseRecallState):
    assert dense_recall_state.aembed_call_count == 0


@then("不调用 Qdrant 客户端")
def _then_qdrant_not_called(dense_recall_state: _DenseRecallState):
    assert dense_recall_state.qdrant_search_call_count == 0


@then("抛出 ValueError")
def _then_value_error(dense_recall_state: _DenseRecallState):
    assert isinstance(dense_recall_state.error, ValueError), f"got {dense_recall_state.error!r}"


@then("抛出 VectorRetrievalConfigurationError")
def _then_config_error(dense_recall_state: _DenseRecallState):
    assert isinstance(
        dense_recall_state.error,
        VectorRetrievalConfigurationError,
    ), f"got {dense_recall_state.error!r}"


@then("抛出 VectorRetrievalEncodingError")
def _then_encoding_error(dense_recall_state: _DenseRecallState):
    assert isinstance(
        dense_recall_state.error,
        VectorRetrievalEncodingError,
    ), f"got {dense_recall_state.error!r}"


@then("抛出 VectorRetrievalBackendError")
def _then_backend_error(dense_recall_state: _DenseRecallState):
    assert isinstance(
        dense_recall_state.error,
        VectorRetrievalBackendError,
    ), f"got {dense_recall_state.error!r}"


@then("不抛任何异常")
def _then_no_error(dense_recall_state: _DenseRecallState):
    assert dense_recall_state.error is None, f"unexpected error: {dense_recall_state.error!r}"


@then("两次返回 hits 中 chunk_id 集合相同")
def _then_idempotent_hits(dense_recall_state: _DenseRecallState):
    first = {h.chunk_id for h in dense_recall_state.result_first.hits}
    second = {h.chunk_id for h in dense_recall_state.result_second.hits}
    assert first == second


@then("两次调用过程中不发生 Qdrant 写操作")
def _then_no_qdrant_write(dense_recall_state: _DenseRecallState):
    dense_recall_state.qdrant_store.upsert_points.assert_not_called()
    dense_recall_state.qdrant_store.update_vectors.assert_not_called()
    dense_recall_state.qdrant_store.delete_points.assert_not_called()


# ---------------------------------------------------------------------------
# Then: 对外暴露面
# ---------------------------------------------------------------------------


@then("从 vector_storage 包可以导入 VectorStorageFacade")
def _then_can_import_facade():
    from src.core.vector_storage import VectorStorageFacade as F  # noqa: F401


@then("从 vector_storage 包可以导入 VectorSearchHit, VectorSearchResult")
def _then_can_import_dataclasses():
    from src.core.vector_storage import VectorSearchHit as H  # noqa: F401
    from src.core.vector_storage import VectorSearchResult as R


@then("从 vector_storage 包可以导入召回侧异常族")
def _then_can_import_exceptions():
    from src.core.vector_storage import VectorRetrievalBackendError as B  # noqa: F401
    from src.core.vector_storage import VectorRetrievalConfigurationError as C
    from src.core.vector_storage import VectorRetrievalEncodingError as E
    from src.core.vector_storage import VectorRetrievalError as Base


@then("DenseVectorSearchRequest 不在 vector_storage 包的 __all__ 中")
def _then_request_not_in_all():
    import src.core.vector_storage as vs

    assert "DenseVectorSearchRequest" not in vs.__all__


@then("DenseQueryVectorSpec 不在 vector_storage 包的 __all__ 中")
def _then_spec_not_in_all():
    import src.core.vector_storage as vs

    assert "DenseQueryVectorSpec" not in vs.__all__


@then("VectorRetrieval 异常族继承关系正确")
def _then_exception_hierarchy():
    assert issubclass(VectorRetrievalConfigurationError, VectorRetrievalError)
    assert issubclass(VectorRetrievalBackendError, VectorRetrievalError)
    assert issubclass(VectorRetrievalEncodingError, VectorRetrievalError)


# ---------------------------------------------------------------------------
# Then: aembed_query 直调断言
# ---------------------------------------------------------------------------


@then("底层 embedder.embed 被调用一次")
def _then_embedder_called_once(dense_recall_state: _DenseRecallState):
    assert len(dense_recall_state.embedder_calls) == 1


@then(parsers.parse('embedder.embed 入参 texts 等于 "{text}"'))
def _then_embedder_texts(dense_recall_state: _DenseRecallState, text: str):
    assert dense_recall_state.embedder_calls[-1]["texts"] == [text]


@then("embedder.embed 入参 model 等于 settings.SYSTEM_LLM_MODEL_EMBEDDING")
def _then_embedder_model(dense_recall_state: _DenseRecallState):
    assert dense_recall_state.embedder_calls[-1]["model"] == settings.SYSTEM_LLM_MODEL_EMBEDDING


@then("aembed_query 不写入 embedding_cache")
def _then_no_cache_write(dense_recall_state: _DenseRecallState):
    assert dense_recall_state.aembed_pipeline.embedding_cache == {}


@then("aembed_query 不更新 last_stats")
def _then_no_stats_update(dense_recall_state: _DenseRecallState):
    # last_stats.total_chunks 在构造时初始化为 0；aembed_query 不应更新它
    assert dense_recall_state.aembed_pipeline.last_stats.total_chunks == 0


@then("直接调用 aembed_query 抛出 ValueError")
def _then_aembed_value_error(dense_recall_state: _DenseRecallState):
    assert isinstance(
        dense_recall_state.embed_error,
        ValueError,
    ), f"got {dense_recall_state.embed_error!r}"


@then("不调用底层 embedder")
def _then_embedder_not_called(dense_recall_state: _DenseRecallState):
    assert dense_recall_state.embedder_calls == []


# ---------------------------------------------------------------------------
# Then: DenseRetriever 断言
# ---------------------------------------------------------------------------


@then(parsers.parse('DenseRetriever.source 等于 "{value}"'))
def _then_dense_source(value: str):
    assert DenseRetriever.source == value


@then("DenseRetriever.source 等同于 SOURCE_DENSE")
def _then_dense_source_eq_const():
    assert DenseRetriever.source == SOURCE_DENSE


@then("facade.search_dense_chunks 被调用一次")
def _then_facade_called_once(dense_recall_state: _DenseRecallState):
    assert dense_recall_state.facade_call_count == 1


@then(parsers.parse('facade.search_dense_chunks 入参 query 等于 "{value}"'))
def _then_facade_query(dense_recall_state: _DenseRecallState, value: str):
    assert dense_recall_state.facade_call_kwargs_list[-1]["query"] == value


@then(parsers.parse("facade.search_dense_chunks 入参 user_id 等于 {value:d}"))
def _then_facade_user_id(dense_recall_state: _DenseRecallState, value: int):
    assert dense_recall_state.facade_call_kwargs_list[-1]["user_id"] == value


@then(parsers.parse("facade.search_dense_chunks 入参 set_id 等于 {value:d}"))
def _then_facade_set_id(dense_recall_state: _DenseRecallState, value: int):
    assert dense_recall_state.facade_call_kwargs_list[-1]["set_id"] == value


@then(parsers.parse("facade.search_dense_chunks 入参 top_k 等于 {value:d}"))
def _then_facade_top_k(dense_recall_state: _DenseRecallState, value: int):
    assert dense_recall_state.facade_call_kwargs_list[-1]["top_k"] == value


@then(parsers.parse("facade.search_dense_chunks 入参 score_threshold 等于 {value:f}"))
def _then_facade_threshold(dense_recall_state: _DenseRecallState, value: float):
    assert dense_recall_state.facade_call_kwargs_list[-1]["score_threshold"] == value


@then("facade.search_dense_chunks 入参 doc_id 为 None")
def _then_facade_doc_id_none(dense_recall_state: _DenseRecallState):
    assert dense_recall_state.facade_call_kwargs_list[-1]["doc_id"] is None


@then(parsers.parse("facade.search_dense_chunks 被调用次数等于 {n:d}"))
def _then_facade_call_count(dense_recall_state: _DenseRecallState, n: int):
    assert dense_recall_state.facade_call_count == n


@then(parsers.parse('facade.search_dense_chunks 调用 set_id 顺序等于 "{ids}"'))
def _then_facade_set_id_order(dense_recall_state: _DenseRecallState, ids: str):
    expected = [int(x.strip()) for x in ids.split(",") if x.strip()]
    actual = [c["set_id"] for c in dense_recall_state.facade_call_kwargs_list]
    assert actual == expected


@then(parsers.parse("返回 list[RetrieverHit] 长度等于 {n:d}"))
def _then_retriever_hits_len(dense_recall_state: _DenseRecallState, n: int):
    assert dense_recall_state.error is None, f"unexpected error: {dense_recall_state.error!r}"
    assert len(dense_recall_state.retriever_result) == n


@then(parsers.parse('返回 list[RetrieverHit][0] chunk_id 等于 "{value}"'))
def _then_retriever_hit0_chunk_id(dense_recall_state: _DenseRecallState, value: str):
    assert dense_recall_state.retriever_result[0].chunk_id == value


@then(parsers.parse("返回 list[RetrieverHit][0] doc_id 等于 {value:d}"))
def _then_retriever_hit0_doc_id(dense_recall_state: _DenseRecallState, value: int):
    assert dense_recall_state.retriever_result[0].doc_id == value


@then(parsers.parse("返回 list[RetrieverHit][0] dataset_id 等于 {value:d}"))
def _then_retriever_hit0_dataset_id(dense_recall_state: _DenseRecallState, value: int):
    assert dense_recall_state.retriever_result[0].dataset_id == value


@then(parsers.parse("返回 list[RetrieverHit][0] score 等于 {value:f}"))
def _then_retriever_hit0_score(dense_recall_state: _DenseRecallState, value: float):
    assert dense_recall_state.retriever_result[0].score == value


@then(parsers.parse('返回 list[RetrieverHit][0] source 等于 "{value}"'))
def _then_retriever_hit0_source(dense_recall_state: _DenseRecallState, value: str):
    assert dense_recall_state.retriever_result[0].source == value


@then("返回 list[RetrieverHit] 按 score 降序")
def _then_retriever_sorted(dense_recall_state: _DenseRecallState):
    scores = [h.score for h in dense_recall_state.retriever_result]
    assert scores == sorted(scores, reverse=True)


@then(parsers.parse("返回 list[RetrieverHit] 长度不超过 {n:d}"))
def _then_retriever_len_le(dense_recall_state: _DenseRecallState, n: int):
    assert len(dense_recall_state.retriever_result) <= n


@then("返回 list[RetrieverHit] 等于 空列表")
def _then_retriever_empty(dense_recall_state: _DenseRecallState):
    assert dense_recall_state.retriever_result == []


@then("不调用 facade.search_dense_chunks")
def _then_facade_not_called(dense_recall_state: _DenseRecallState):
    assert dense_recall_state.facade_call_count == 0


# ---------------------------------------------------------------------------
# Then: provider 断言
# ---------------------------------------------------------------------------


@then(parsers.parse('provider 的 _BUILDERS 含键 "{key}"'))
def _then_builders_has_key(key: str):
    from src.api.recall_pipeline_provider import _BUILDERS

    assert key in _BUILDERS


@then(parsers.parse('provider 的 _BUILDERS 键集合等于 "{keys}"'))
def _then_builders_keys_eq(keys: str):
    from src.api.recall_pipeline_provider import _BUILDERS

    expected = {k.strip() for k in keys.split(",") if k.strip()}
    assert set(_BUILDERS.keys()) == expected


@then("provider 内部返回 None 表示未注册")
def _then_provider_lookup_none(dense_recall_state: _DenseRecallState):
    assert dense_recall_state.provider_lookup_result is None
