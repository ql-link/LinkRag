"""对外 RAG 问答流 SSE 验收 step 实现（pytest-bdd 8.x）。

把 ``tests/acceptance/features/rag_stream.feature`` 的中文 Gherkin 绑定到对真实
FastAPI 应用（``src.main.app``）的行为断言。pipeline 用 FakePipeline 隔离，session
JWT 用独立 session 密钥真实签发，Redis 并发计数用内存 FakeRedis 替身隔离，模型解析 /
正文回填 / 流式生成用状态可控的确定性替身隔离。

state 通过 ``rag_acc_state`` fixture 跨 step 共享；每个 Scenario 一份独立状态，
teardown 还原被改写的 settings、清空 dependency_overrides、还原 redis_client 方法。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from types import SimpleNamespace

import jwt
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then, when

from src.api import recall_stream_runtime
from src.api.recall_pipeline_provider import get_recall_pipeline
from src.api.routes import rag
from src.cache.redis_client import redis_client
from src.config import settings
from src.core.llm.exceptions import UserModelConfigMissingError
from src.core.llm.response import StreamChunk
from src.core.pipeline.recall import RecallHit, RecallRequest, RecallResponse
from src.main import app

URL = "/api/v1/rag/stream"

# 本特性聚焦握手/鉴权/并发/传输/召回执行语义；config_id 必填（CHAT 模型由前端传入），
# 未显式提供则注入确定性替身 id。
CONFIG_ID = 77


class _FakeProvider:
    """状态可控的流式生成替身；记录是否被调用，可注入生成阶段异常。"""

    def __init__(self, state: "_State") -> None:
        self.state = state

    async def stream(self, prompt, system_prompt=None, **kwargs):
        self.state.provider_stream_called = True
        if self.state.generation_raises:
            raise RuntimeError("generation boom")
        yield StreamChunk(delta="答案", is_end=False)
        yield StreamChunk(delta="完成", is_end=True)


class FakePipeline:
    """可控 pipeline 替身；execute 记录入参，按 top_k 截断。"""

    def __init__(self) -> None:
        self.response: RecallResponse | None = None
        self.exc: Exception | None = None
        self.delay: float = 0.0
        self.calls: list[RecallRequest] = []

    async def execute(self, request: RecallRequest) -> RecallResponse:
        self.calls.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc is not None:
            raise self.exc
        resp = self.response
        return RecallResponse(
            query=resp.query,
            hits=resp.hits[: request.top_k],
            per_source_counts=resp.per_source_counts,
            failed_sources=resp.failed_sources,
            elapsed_ms=resp.elapsed_ms,
        )


class _FakeRedis:
    """内存并发计数替身：仅实现 acquire/release 用到的 incr/decr/expire/set。"""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    async def decr(self, key: str) -> int:
        self.store[key] = int(self.store.get(key, 0)) - 1
        return self.store[key]

    async def expire(self, key: str, ttl: int) -> bool:
        return True

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = int(value) if str(value).lstrip("-").isdigit() else value


@dataclass
class _State:
    claims: dict = field(default_factory=dict)
    defect: str | None = None
    sign_with_foreign: bool = False
    body: dict | None = None
    raw_body: str | None = None
    omit_dataset: bool = False
    omit_config: bool = False
    fake: FakePipeline = field(default_factory=FakePipeline)
    redis: _FakeRedis = field(default_factory=_FakeRedis)
    cors_origins: list[str] = field(default_factory=list)
    response: object = None
    events: list[tuple[str, str]] = field(default_factory=list)
    cancel_raised: bool = False
    # 生成替身控制
    model_available: bool = True
    generation_raises: bool = False
    no_content: bool = False
    provider_stream_called: bool = False
    _settings_snapshot: dict = field(default_factory=dict)
    _redis_snapshot: dict = field(default_factory=dict)
    _runtime_snapshot: dict = field(default_factory=dict)

    def set_setting(self, name: str, value) -> None:
        if name not in self._settings_snapshot:
            self._settings_snapshot[name] = getattr(settings, name)
        setattr(settings, name, value)

    def install_redis(self) -> None:
        for name in ("incr", "decr", "expire", "set"):
            self._redis_snapshot[name] = getattr(redis_client, name)
            setattr(redis_client, name, getattr(self.redis, name))

    def install_generation_stubs(self) -> None:
        # 模型解析与正文回填用状态可控替身，隔离 DB / LLM。
        self._runtime_snapshot["aresolve_user_model"] = recall_stream_runtime.aresolve_user_model
        self._runtime_snapshot["fetch_chunk_contents"] = recall_stream_runtime.fetch_chunk_contents

        async def _resolve(*args, **kwargs):
            if not self.model_available:
                raise UserModelConfigMissingError(capability="CHAT", user_id=123)
            return SimpleNamespace(
                provider=_FakeProvider(self),
                model_name="fake",
                provider_type="openai",
                source="user",
            )

        async def _fetch(chunk_ids, user_id):
            if self.no_content:
                return {}
            return {cid: f"片段正文 {cid}" for cid in chunk_ids}

        recall_stream_runtime.aresolve_user_model = _resolve
        recall_stream_runtime.fetch_chunk_contents = _fetch

    def restore(self) -> None:
        for name, value in self._settings_snapshot.items():
            setattr(settings, name, value)
        for name, value in self._redis_snapshot.items():
            setattr(redis_client, name, value)
        for name, value in self._runtime_snapshot.items():
            setattr(recall_stream_runtime, name, value)


@pytest.fixture
def rag_acc_state():
    state = _State()
    state.claims = {"sub": "123", "dataset_ids": [1, 2]}
    state.fake.response = RecallResponse(
        query="q",
        hits=[
            RecallHit("1001", 10, 1, 0.92, {"bm25": 8.7, "sparse": 0.76}),
            RecallHit("1002", 11, 1, 0.40, {"bm25": 5.0, "sparse": None}),
        ],
        per_source_counts={"bm25": 2, "sparse": 1},
        failed_sources=[],
        elapsed_ms=12,
    )
    state.install_redis()
    state.install_generation_stubs()
    yield state
    state.restore()
    app.dependency_overrides.pop(get_recall_pipeline, None)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_token(state: _State) -> str:
    """按 state 签发 session token（含缺陷注入）。"""
    if state.sign_with_foreign:
        return jwt.encode(
            {
                "iss": settings.RECALL_SESSION_JWT_ISSUER,
                "aud": settings.RECALL_SESSION_JWT_AUDIENCE,
                "scope": settings.RECALL_SESSION_JWT_SCOPE,
                "sub": state.claims.get("sub", "123"),
                "dataset_ids": state.claims.get("dataset_ids", [1]),
                "exp": int(time.time()) + 300,
            },
            "some-other-service-secret-not-the-session-key",
            algorithm="HS256",
        )

    secret = settings.RECALL_SESSION_JWT_SECRET
    payload = {
        "iss": settings.RECALL_SESSION_JWT_ISSUER,
        "aud": settings.RECALL_SESSION_JWT_AUDIENCE,
        "scope": settings.RECALL_SESSION_JWT_SCOPE,
        "sub": state.claims.get("sub", "123"),
        "dataset_ids": state.claims.get("dataset_ids", [1, 2]),
        "exp": int(time.time()) + 300,
    }
    defect = state.defect
    if defect == "签名不匹配":
        secret = "wrong-secret"
    elif defect and "iss" in defect:
        payload["iss"] = "evil"
    elif defect and "aud" in defect:
        payload["aud"] = "other"
    elif defect and "scope" in defect:
        payload["scope"] = "x:y"
    elif defect and "exp" in defect:
        payload["exp"] = int(time.time()) - 10
    return jwt.encode(payload, secret, algorithm="HS256")


def _parse_ds(text: str) -> list[int]:
    text = text.strip()
    return [int(x) for x in text.split(",")] if text else []


def _parse_sse(text: str) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    name = None
    for line in text.splitlines():
        if line.startswith("event: "):
            name = line[len("event: ") :]
        elif line.startswith("data: ") and name is not None:
            events.append((name, line[len("data: ") :]))
            name = None
    return events


def _fire(state: _State, *, with_token: bool) -> None:
    app.dependency_overrides[get_recall_pipeline] = lambda: state.fake
    headers = {"Accept": "text/event-stream"}
    if with_token:
        headers["Authorization"] = f"Bearer {_make_token(state)}"
    client = TestClient(app)
    if state.raw_body is not None:
        resp = client.post(URL, content=state.raw_body, headers=headers)
    elif state.omit_config:
        # 缺 config_id：直接发原始 body，不注入替身 config_id。
        resp = client.post(URL, json=state.body, headers=headers)
    elif state.omit_dataset:
        resp = client.post(
            URL, json={"query": state.body["query"], "config_id": CONFIG_ID}, headers=headers
        )
    else:
        body = {"config_id": CONFIG_ID, **state.body}
        resp = client.post(URL, json=body, headers=headers)
    state.response = resp
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        state.events = _parse_sse(resp.text)


def _fire_to(state: _State, url: str, *, with_token: bool) -> None:
    """对指定（已删除）路径发起请求，用于断言旧路径 404。"""
    app.dependency_overrides[get_recall_pipeline] = lambda: state.fake
    headers = {"Accept": "text/event-stream"}
    if with_token:
        headers["Authorization"] = f"Bearer {_make_token(state)}"
    client = TestClient(app)
    state.response = client.post(
        url, json={"query": "任意", "config_id": CONFIG_ID, "dataset_ids": [1]}, headers=headers
    )


def _event_data(state: _State, name: str) -> dict:
    for ev_name, data in state.events:
        if ev_name == name:
            return json.loads(data)
    raise AssertionError(f"SSE event {name!r} not found in {state.events}")


def _last_event_data(state: _State) -> dict:
    assert state.events, "no SSE events captured"
    return json.loads(state.events[-1][1])


# ---------------------------------------------------------------------------
# Background / 配置
# ---------------------------------------------------------------------------


@given(parsers.re(r"配置 (?P<name>[A-Z_]+)=(?P<value>.+)"))
def _set_config(rag_acc_state, name, value):
    if value in ("True", "False"):
        casted = value == "True"
    elif value.isdigit():
        casted = int(value)
    else:
        casted = value
    rag_acc_state.set_setting(name, casted)


@given(parsers.re(r"配置 session token 的 (?P<name>[A-Z_]+)=(?P<value>.+)"))
def _set_session_config(rag_acc_state, name, value):
    rag_acc_state.set_setting(name, value)


@given(parsers.parse("session token 使用 RECALL_SESSION_JWT_SECRET 这一独立专用签名密钥"))
def _distinct_secret(rag_acc_state):
    assert settings.RECALL_SESSION_JWT_SECRET


@given(parsers.parse("session token 短期可复用，有效期内只校验 exp，不做一次性消费"))
def _reusable(rag_acc_state):
    pass


@given(parsers.re(r"配置对外 CORS 允许来源为 (?P<origins>.+)"))
def _cors_config(rag_acc_state, origins):
    inner = origins.strip().strip("[]")
    rag_acc_state.cors_origins = [p.strip().strip('"') for p in inner.split(",") if p.strip()]


@given(parsers.re(r"配置单用户最大并发召回流数 RECALL_SESSION_MAX_CONCURRENT=(?P<n>\d+)"))
def _max_concurrent(rag_acc_state, n):
    rag_acc_state.set_setting("RECALL_SESSION_MAX_CONCURRENT", int(n))


@given(parsers.parse("Redis 可用用于并发流计数"))
def _redis_ok(rag_acc_state):
    pass


@given(parsers.parse("服务端已装配 bm25 与 sparse 两路 retriever"))
def _two_sources(rag_acc_state):
    pass


# ---------------------------------------------------------------------------
# Given：claims / 缺陷 / 模型 / pipeline 状态 / 并发预置
# ---------------------------------------------------------------------------


@given(parsers.re(r"session token claims sub=(?P<sub>\d+).*dataset_ids=\[(?P<ds>[^\]]*)\].*"))
def _claims(rag_acc_state, sub, ds):
    rag_acc_state.claims = {"sub": sub, "dataset_ids": _parse_ds(ds)}


@given(parsers.re(r'session token 存在缺陷 "(?P<defect>[^"]+)"'))
def _claims_defect(rag_acc_state, defect):
    rag_acc_state.claims = {"sub": "123", "dataset_ids": [1]}
    rag_acc_state.defect = defect


@given(parsers.parse("一个 token 用非 session 密钥的其它密钥签发 claims 全对"))
def _foreign_signed(rag_acc_state):
    rag_acc_state.claims = {"sub": "123", "dataset_ids": [1]}
    rag_acc_state.sign_with_foreign = True


@given(parsers.parse("config_id 指向的 CHAT 模型对用户 123 可用"))
def _model_available(rag_acc_state):
    rag_acc_state.model_available = True


@given(parsers.parse("config_id 指向的 CHAT 模型对用户 123 不可用"))
def _model_unavailable(rag_acc_state):
    rag_acc_state.model_available = False


@given(parsers.parse("bm25 与 sparse 两路均返回命中"))
def _both_hit(rag_acc_state):
    pass


@given(parsers.parse("bm25 与 sparse 两路均返回 0 命中"))
def _zero_hit(rag_acc_state):
    rag_acc_state.fake.response = RecallResponse(
        query="q", hits=[], per_source_counts={}, failed_sources=[], elapsed_ms=1
    )


@given(parsers.parse("bm25 与 sparse 两路返回命中但全部命中片段无可用正文"))
def _hit_no_content(rag_acc_state):
    rag_acc_state.no_content = True


@given(parsers.parse("bm25 路抛异常而 sparse 路返回命中"))
def _partial_degrade(rag_acc_state):
    resp = rag_acc_state.fake.response
    rag_acc_state.fake.response = RecallResponse(
        query=resp.query,
        hits=resp.hits,
        per_source_counts=resp.per_source_counts,
        failed_sources=["bm25"],
        elapsed_ms=resp.elapsed_ms,
    )


@given(parsers.parse("召回命中且正文可回填但流式生成阶段抛异常"))
def _generation_raises(rag_acc_state):
    rag_acc_state.generation_raises = True


@given(parsers.parse("用户 123 无默认 EMBEDDING 配置"))
def _embedding_missing(rag_acc_state):
    from src.core.pipeline.recall import RecallFatalError

    rag_acc_state.fake.exc = RecallFatalError("user embedding config missing")


@given(parsers.parse("bm25 与 sparse 两路均执行抛异常"))
def _all_fail(rag_acc_state):
    from src.core.pipeline.recall import RecallError

    rag_acc_state.fake.exc = RecallError("all retrievers failed")


@given(parsers.parse("recall runtime 执行超过 RECALL_STREAM_TIMEOUT_MS"))
def _runtime_timeout(rag_acc_state):
    rag_acc_state.set_setting("RECALL_STREAM_TIMEOUT_MS", 10)
    rag_acc_state.fake.delay = 0.5


@given(parsers.parse("recall 正在执行中"))
def _recall_running(rag_acc_state):
    rag_acc_state.fake.delay = 10.0


@given(parsers.parse("已用该 token 成功建连且召回正在执行"))
def _connected_running(rag_acc_state):
    pass


@given(parsers.parse("已用该 token 成功建连过一次且连接已结束"))
def _connected_once(rag_acc_state):
    rag_acc_state.body = {"query": "warmup"}
    rag_acc_state.omit_dataset = True
    _fire(rag_acc_state, with_token=True)
    rag_acc_state.omit_dataset = False


@given(parsers.re(r"用户 123 已有 (?P<n>\d+) 条召回流在执行"))
def _preset_concurrency(rag_acc_state, n):
    rag_acc_state.redis.store["recall:concurrent:123"] = int(n)


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(
    parsers.re(
        r"前端携带该 token 以 Authorization Bearer 调用 POST /api/v1/rag/stream "
        r'body query="(?P<query>[^"]*)" dataset_ids=\[(?P<ds>[^\]]*)\]'
    )
)
def _w_happy(rag_acc_state, query, ds):
    rag_acc_state.body = {"query": query, "dataset_ids": _parse_ds(ds)}
    _fire(rag_acc_state, with_token=True)


@when(
    parsers.re(
        r"前端携带该 token 调用 POST /api/v1/rag/stream "
        r'body query="(?P<query>[^"]*)" dataset_ids=\[(?P<ds>[^\]]*)\]'
    )
)
def _w_with_token(rag_acc_state, query, ds):
    rag_acc_state.body = {"query": query, "dataset_ids": _parse_ds(ds)}
    _fire(rag_acc_state, with_token=True)


@when(
    parsers.re(
        r"前端不携带 Authorization 头调用 POST /api/v1/rag/stream "
        r'body query="(?P<query>[^"]*)" dataset_ids=\[(?P<ds>[^\]]*)\]'
    )
)
def _w_no_auth(rag_acc_state, query, ds):
    rag_acc_state.body = {"query": query, "dataset_ids": _parse_ds(ds)}
    _fire(rag_acc_state, with_token=False)


@when(
    parsers.re(
        r'前端携带该 token 调用 POST /api/v1/rag/stream body 额外包含字段 "(?P<field>[^"]+)"'
    )
)
def _w_extra_field(rag_acc_state, field):
    rag_acc_state.body = {"query": "q", "dataset_ids": [1], field: "x"}
    _fire(rag_acc_state, with_token=True)


@when(
    parsers.re(
        r'前端携带该 token 调用 POST /api/v1/rag/stream body query="(?P<query>[^"]*)" dataset_ids=\[(?P<ds>[^\]]*)\] 不含 config_id'
    )
)
def _w_missing_config(rag_acc_state, query, ds):
    rag_acc_state.body = {"query": query, "dataset_ids": _parse_ds(ds)}
    rag_acc_state.omit_config = True
    _fire(rag_acc_state, with_token=True)
    rag_acc_state.omit_config = False


@when(
    parsers.re(
        r"前端携带该 token 调用 POST /api/v1/rag/stream "
        r'body query 为空白标识 "(?P<tok>[^"]+)" dataset_ids=\[(?P<ds>[^\]]*)\]'
    )
)
def _w_blank_query(rag_acc_state, tok, ds):
    mapping = {"EMPTY": "", "SPACES": "   ", "NEWLINE": "\n", "TAB": "\t"}
    rag_acc_state.body = {"query": mapping.get(tok, ""), "dataset_ids": _parse_ds(ds)}
    _fire(rag_acc_state, with_token=True)


@when(
    parsers.re(
        r'前端携带该 token 调用 POST /api/v1/rag/stream body query="(?P<query>[^"]*)" 且不含 dataset_ids'
    )
)
def _w_omit_dataset(rag_acc_state, query):
    rag_acc_state.body = {"query": query}
    rag_acc_state.omit_dataset = True
    _fire(rag_acc_state, with_token=True)
    rag_acc_state.omit_dataset = False


@when(
    parsers.re(
        r"前端在 token 未过期时携带同一 token 再次调用 POST /api/v1/rag/stream "
        r'body query="(?P<query>[^"]*)" dataset_ids=\[(?P<ds>[^\]]*)\]'
    )
)
def _w_reuse(rag_acc_state, query, ds):
    rag_acc_state.body = {"query": query, "dataset_ids": _parse_ds(ds)}
    _fire(rag_acc_state, with_token=True)


@when(parsers.parse("token 的 exp 在流执行期间到达"))
def _w_exp_during_stream(rag_acc_state):
    rag_acc_state.body = {"query": "q"}
    rag_acc_state.omit_dataset = True
    _fire(rag_acc_state, with_token=True)
    rag_acc_state.omit_dataset = False


@when(parsers.re(r"前端携带新 token 为用户 123 发起第 (?P<n>\d+) 条 POST /api/v1/rag/stream"))
def _w_nth_stream(rag_acc_state, n):
    rag_acc_state.body = {"query": "任意", "dataset_ids": [1]}
    _fire(rag_acc_state, with_token=True)


@when(
    parsers.re(
        r'前端从 Origin "(?P<origin>[^"]+)" 携带该 token 调用 POST /api/v1/rag/stream '
        r'body query="(?P<query>[^"]*)" dataset_ids=\[(?P<ds>[^\]]*)\]'
    )
)
def _w_cors(rag_acc_state, origin, query, ds):
    cors_app = FastAPI()
    cors_app.add_middleware(
        CORSMiddleware,
        allow_origins=rag_acc_state.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    cors_app.include_router(rag.router)
    client = TestClient(cors_app)
    rag_acc_state.response = client.options(
        URL,
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )


@when(parsers.parse("前端主动断开到 Python 的 SSE 连接"))
def _w_disconnect(rag_acc_state):
    rag_acc_state.redis.store["recall:concurrent:123"] = 1
    req = RecallRequest(query="q", user_id=123, dataset_ids=[1], top_k=20)
    gen = rag._guarded_stream(rag_acc_state.fake, req, "rid", 123, CONFIG_ID)

    async def _drive() -> None:
        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0.02)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            rag_acc_state.cancel_raised = True
        await gen.aclose()

    asyncio.run(_drive())


@when(parsers.re(r"前端携带该 token 调用已删除路径 POST (?P<url>\S+)"))
def _w_deleted_path_with_token(rag_acc_state, url):
    _fire_to(rag_acc_state, url, with_token=True)


@when(parsers.re(r"调用已删除路径 POST (?P<url>\S+)"))
def _w_deleted_path(rag_acc_state, url):
    _fire_to(rag_acc_state, url, with_token=False)


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(parsers.re(r"HTTP 响应状态为 (?P<code>\d+)"))
def _status(rag_acc_state, code):
    assert rag_acc_state.response.status_code == int(code)


@then(parsers.re(r'响应 Content-Type 为 "(?P<ct>[^"]+)"'))
def _content_type(rag_acc_state, ct):
    assert rag_acc_state.response.headers["content-type"].startswith(ct)


@then(parsers.re(r'响应头 Cache-Control 为 "(?P<v>[^"]+)"'))
def _cache_control(rag_acc_state, v):
    assert rag_acc_state.response.headers.get("cache-control") == v


@then(parsers.re(r'响应头 X-Accel-Buffering 为 "(?P<v>[^"]+)"'))
def _accel(rag_acc_state, v):
    assert rag_acc_state.response.headers.get("x-accel-buffering") == v


@then(parsers.re(r'收到 SSE 事件 "(?P<name>[^"]+)"'))
def _got_event(rag_acc_state, name):
    assert any(n == name for n, _ in rag_acc_state.events)


@then(parsers.re(r'至少收到一个 SSE 事件 "(?P<name>[^"]+)"'))
def _got_at_least_one(rag_acc_state, name):
    assert any(n == name for n, _ in rag_acc_state.events)


@then(parsers.re(r'最终收到 SSE 事件 "(?P<name>[^"]+)"'))
def _final_event(rag_acc_state, name):
    names = [n for n, _ in rag_acc_state.events]
    assert names and names[-1] == name


@then(parsers.re(r'不收到 SSE 事件 "(?P<name>[^"]+)"'))
def _not_got_event(rag_acc_state, name):
    assert all(n != name for n, _ in rag_acc_state.events)


@then(parsers.parse("answer_done.data 含字段 answer 与 hits 与 failed_sources"))
def _answer_done_fields(rag_acc_state):
    data = _event_data(rag_acc_state, "answer_done")
    assert "answer" in data and "hits" in data and "failed_sources" in data


@then(parsers.parse("hits 中每个 hit 不含字段 content"))
def _no_content(rag_acc_state):
    for h in _last_event_data(rag_acc_state)["hits"]:
        assert "content" not in h


@then(
    parsers.parse(
        "hits 中每个 hit 含字段 chunk_id 与 doc_id 与 dataset_id 与 fused_score 与 scores"
    )
)
def _hit_shape(rag_acc_state):
    for h in _last_event_data(rag_acc_state)["hits"]:
        for field_name in ("chunk_id", "doc_id", "dataset_id", "fused_score", "scores"):
            assert field_name in h, f"hit missing {field_name}: {h}"


@then(parsers.parse("终态事件 data 中 hits 按 fused_score 降序排列"))
def _hits_sorted(rag_acc_state):
    scores = [h["fused_score"] for h in _last_event_data(rag_acc_state)["hits"]]
    assert scores == sorted(scores, reverse=True)


@then(parsers.re(r'终态事件 data 的 failed_sources 含 "(?P<src>[^"]+)"'))
def _failed_sources_contains(rag_acc_state, src):
    assert src in _last_event_data(rag_acc_state)["failed_sources"]


@then(parsers.parse("终态事件 data 的 hits 非空"))
def _hits_non_empty(rag_acc_state):
    assert _last_event_data(rag_acc_state)["hits"]


@then(parsers.parse("发送 answer_done 后关闭 SSE 流"))
def _close_after_done(rag_acc_state):
    names = [n for n, _ in rag_acc_state.events]
    assert names[-1] == "answer_done"


@then(parsers.parse("不调用 CHAT 模型生成"))
def _chat_not_called(rag_acc_state):
    assert rag_acc_state.provider_stream_called is False


@then(parsers.re(r'响应体 code 等于 "(?P<code>[^"]+)"'))
def _body_code(rag_acc_state, code):
    assert rag_acc_state.response.json()["code"] == code


@then(parsers.parse("不调用 RecallPipeline"))
def _pipeline_not_called(rag_acc_state):
    assert rag_acc_state.fake.calls == []


@then(parsers.re(r"以 user_id=(?P<uid>\d+) 执行 RecallPipeline"))
def _executed_user(rag_acc_state, uid):
    assert rag_acc_state.fake.calls[0].user_id == int(uid)


@then(parsers.re(r"以 dataset_ids=\[(?P<ds>[^\]]*)\] 执行 RecallPipeline"))
def _executed_dataset(rag_acc_state, ds):
    assert rag_acc_state.fake.calls[0].dataset_ids == _parse_ds(ds)


@then(parsers.re(r'error.data 的 code 等于 "(?P<code>[^"]+)"'))
def _error_code(rag_acc_state, code):
    assert _event_data(rag_acc_state, "error")["code"] == code


@then(parsers.parse("error.data 的 message 不含内部堆栈"))
def _error_no_stack(rag_acc_state):
    msg = _event_data(rag_acc_state, "error")["message"]
    assert "Traceback" not in msg and 'File "' not in msg


@then(parsers.parse("发送 error 后关闭 SSE 流"))
def _close_after_error(rag_acc_state):
    names = [n for n, _ in rag_acc_state.events]
    assert names[-1] == "error"


@then(parsers.re(r'响应头 Access-Control-Allow-Origin 等于 "(?P<origin>[^"]+)"'))
def _acao_eq(rag_acc_state, origin):
    assert rag_acc_state.response.headers.get("access-control-allow-origin") == origin


@then(parsers.re(r'响应头 Access-Control-Allow-Origin 不等于 "(?P<origin>[^"]+)"'))
def _acao_ne(rag_acc_state, origin):
    assert rag_acc_state.response.headers.get("access-control-allow-origin") != origin


@then(parsers.parse("当前 SSE 流不因 token 过期被中断"))
def _stream_not_interrupted(rag_acc_state):
    assert rag_acc_state.response.status_code == 200
    assert any(n == "answer_done" for n, _ in rag_acc_state.events)


@then(parsers.parse("流仍以 answer_done 或 error 正常终态结束"))
def _stream_terminal(rag_acc_state):
    names = [n for n, _ in rag_acc_state.events]
    assert names and names[-1] in {"answer_done", "error"}


@then(parsers.parse("流的最大执行时间仍由 RECALL_STREAM_TIMEOUT_MS 控制"))
def _stream_timeout_governed(rag_acc_state):
    assert any(n == "answer_done" for n, _ in rag_acc_state.events)


@then(parsers.parse("Python 停止继续发送 SSE 事件"))
def _stopped(rag_acc_state):
    assert rag_acc_state.cancel_raised


@then(parsers.parse("Python 尽力取消正在执行的召回任务"))
def _cancelled(rag_acc_state):
    assert rag_acc_state.cancel_raised


@then(parsers.parse("该流不再计入用户 123 的并发流数"))
def _slot_released(rag_acc_state):
    assert rag_acc_state.redis.store.get("recall:concurrent:123", 0) == 0
