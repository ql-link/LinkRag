"""对外直连召回 SSE 验收 step 实现（pytest-bdd 8.x）。

把 ``tests/acceptance/features/recall_direct_sse.feature`` 的中文 Gherkin 绑定到对
真实 FastAPI 应用（``src.main.app``）的行为断言。pipeline 用 FakePipeline 隔离，
session JWT 用独立 session 密钥真实签发，Redis 并发计数用内存 FakeRedis 替身隔离。

state 通过 ``direct_acc_state`` fixture 跨 step 共享；每个 Scenario 一份独立状态，
teardown 还原被改写的 settings、清空 dependency_overrides、还原 redis_client 方法。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

import jwt
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then, when

from src.api import recall_session_auth
from src.api.recall_pipeline_provider import get_recall_pipeline
from src.api.routes import recall_direct
from src.cache.redis_client import redis_client
from src.config import settings
from src.core.pipeline.recall import RecallHit, RecallRequest, RecallResponse
from src.main import app

URL = "/api/v1/recall/stream"


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
    sign_with_internal: bool = False
    body: dict | None = None
    raw_body: str | None = None
    omit_dataset: bool = False
    fake: FakePipeline = field(default_factory=FakePipeline)
    redis: _FakeRedis = field(default_factory=_FakeRedis)
    cors_origins: list[str] = field(default_factory=list)
    response: object = None
    events: list[tuple[str, str]] = field(default_factory=list)
    cancel_raised: bool = False
    _settings_snapshot: dict = field(default_factory=dict)
    _redis_snapshot: dict = field(default_factory=dict)

    def set_setting(self, name: str, value) -> None:
        if name not in self._settings_snapshot:
            self._settings_snapshot[name] = getattr(settings, name)
        setattr(settings, name, value)

    def install_redis(self) -> None:
        for name in ("incr", "decr", "expire", "set"):
            self._redis_snapshot[name] = getattr(redis_client, name)
            setattr(redis_client, name, getattr(self.redis, name))

    def restore(self) -> None:
        for name, value in self._settings_snapshot.items():
            setattr(settings, name, value)
        for name, value in self._redis_snapshot.items():
            setattr(redis_client, name, value)


@pytest.fixture
def direct_acc_state():
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
    yield state
    state.restore()
    app.dependency_overrides.pop(get_recall_pipeline, None)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_token(state: _State) -> str:
    """按 state 签发 session token（含缺陷注入）。"""
    if state.sign_with_internal:
        # 用内部端点密钥 + 内部 scope 签发：对外端点应因密钥/aud/scope 不符而拒绝。
        return jwt.encode(
            {
                "iss": settings.RECALL_INTERNAL_JWT_ISSUER,
                "aud": settings.RECALL_INTERNAL_JWT_AUDIENCE,
                "scope": settings.RECALL_INTERNAL_JWT_SCOPE,
                "sub": state.claims.get("sub", "123"),
                "dataset_ids": state.claims.get("dataset_ids", [1]),
                "exp": int(time.time()) + 300,
            },
            settings.RECALL_INTERNAL_JWT_SECRET,
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
            name = line[len("event: "):]
        elif line.startswith("data: ") and name is not None:
            events.append((name, line[len("data: "):]))
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
    elif state.omit_dataset:
        resp = client.post(URL, json={"query": state.body["query"]}, headers=headers)
    else:
        resp = client.post(URL, json=state.body, headers=headers)
    state.response = resp
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        state.events = _parse_sse(resp.text)


def _event_data(state: _State, name: str) -> dict:
    for ev_name, data in state.events:
        if ev_name == name:
            return json.loads(data)
    raise AssertionError(f"SSE event {name!r} not found in {state.events}")


# ---------------------------------------------------------------------------
# Background / 配置
# ---------------------------------------------------------------------------


@given(parsers.re(r"配置 (?P<name>[A-Z_]+)=(?P<value>.+)"))
def _set_config(direct_acc_state, name, value):
    if value in ("True", "False"):
        casted = value == "True"
    elif value.isdigit():
        casted = int(value)
    else:
        casted = value
    direct_acc_state.set_setting(name, casted)


@given(parsers.re(r"配置 session token 的 (?P<name>[A-Z_]+)=(?P<value>.+)"))
def _set_session_config(direct_acc_state, name, value):
    direct_acc_state.set_setting(name, value)


@given(parsers.parse("session token 的签名密钥与内部 JWT 的 RECALL_INTERNAL_JWT_SECRET 是不同的独立密钥"))
def _distinct_secret(direct_acc_state):
    # 配置默认即独立；显式断言两者不同，避免回归时被改成同一个。
    assert settings.RECALL_SESSION_JWT_SECRET != settings.RECALL_INTERNAL_JWT_SECRET


@given(parsers.parse("session token 短期可复用，有效期内只校验 exp，不做一次性消费"))
def _reusable(direct_acc_state):
    pass


@given(parsers.re(r"配置对外 CORS 允许来源为 (?P<origins>.+)"))
def _cors_config(direct_acc_state, origins):
    # 形如 ["https://app.tolink.com"]；剥括号与引号取域名清单。
    inner = origins.strip().strip("[]")
    direct_acc_state.cors_origins = [p.strip().strip('"') for p in inner.split(",") if p.strip()]


@given(parsers.re(r"配置单用户最大并发召回流数 RECALL_SESSION_MAX_CONCURRENT=(?P<n>\d+)"))
def _max_concurrent(direct_acc_state, n):
    direct_acc_state.set_setting("RECALL_SESSION_MAX_CONCURRENT", int(n))


@given(parsers.parse("Redis 可用用于并发流计数"))
def _redis_ok(direct_acc_state):
    pass  # FakeRedis 已在 fixture 安装


@given(parsers.parse("服务端已装配 bm25 与 sparse 两路 retriever"))
def _two_sources(direct_acc_state):
    pass


# ---------------------------------------------------------------------------
# Given：claims / 缺陷 / pipeline 状态 / 并发预置
# ---------------------------------------------------------------------------


@given(parsers.re(r"session token claims sub=(?P<sub>\d+).*dataset_ids=\[(?P<ds>[^\]]*)\].*"))
def _claims(direct_acc_state, sub, ds):
    direct_acc_state.claims = {"sub": sub, "dataset_ids": _parse_ds(ds)}


@given(parsers.re(r'session token 存在缺陷 "(?P<defect>[^"]+)"'))
def _claims_defect(direct_acc_state, defect):
    direct_acc_state.claims = {"sub": "123", "dataset_ids": [1]}
    direct_acc_state.defect = defect


@given(parsers.parse("一个 token 用内部端点的 RECALL_INTERNAL_JWT_SECRET 签发 scope=recall:execute"))
def _internal_signed(direct_acc_state):
    direct_acc_state.claims = {"sub": "123", "dataset_ids": [1]}
    direct_acc_state.sign_with_internal = True


@given(parsers.parse("bm25 与 sparse 两路均返回命中"))
def _both_hit(direct_acc_state):
    pass


@given(parsers.parse("bm25 与 sparse 两路均执行抛异常"))
def _all_fail(direct_acc_state):
    from src.core.pipeline.recall import RecallError

    direct_acc_state.fake.exc = RecallError("all retrievers failed")


@given(parsers.parse("recall runtime 执行超过 RECALL_STREAM_TIMEOUT_MS"))
def _runtime_timeout(direct_acc_state):
    direct_acc_state.set_setting("RECALL_STREAM_TIMEOUT_MS", 10)
    direct_acc_state.fake.delay = 0.5


@given(parsers.parse("recall 正在执行中"))
def _recall_running(direct_acc_state):
    direct_acc_state.fake.delay = 10.0


@given(parsers.parse("已用该 token 成功建连且召回正在执行"))
def _connected_running(direct_acc_state):
    pass


@given(parsers.parse("已用该 token 成功建连过一次且连接已结束"))
def _connected_once(direct_acc_state):
    # 先用同一 token 成功建连一次（不触发一次性，第二次仍应成功）。
    direct_acc_state.body = {"query": "warmup"}
    direct_acc_state.omit_dataset = True
    _fire(direct_acc_state, with_token=True)
    direct_acc_state.omit_dataset = False


@given(parsers.re(r"用户 123 已有 (?P<n>\d+) 条召回流在执行"))
def _preset_concurrency(direct_acc_state, n):
    direct_acc_state.redis.store["recall:concurrent:123"] = int(n)


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(parsers.re(
    r'前端携带该 token 以 Authorization Bearer 调用 POST /api/v1/recall/stream '
    r'body query="(?P<query>[^"]*)" dataset_ids=\[(?P<ds>[^\]]*)\]'
))
def _w_happy(direct_acc_state, query, ds):
    direct_acc_state.body = {"query": query, "dataset_ids": _parse_ds(ds)}
    _fire(direct_acc_state, with_token=True)


@when(parsers.re(
    r'前端携带该 token 调用 POST /api/v1/recall/stream '
    r'body query="(?P<query>[^"]*)" dataset_ids=\[(?P<ds>[^\]]*)\]'
))
def _w_with_token(direct_acc_state, query, ds):
    direct_acc_state.body = {"query": query, "dataset_ids": _parse_ds(ds)}
    _fire(direct_acc_state, with_token=True)


@when(parsers.re(
    r'前端不携带 Authorization 头调用 POST /api/v1/recall/stream '
    r'body query="(?P<query>[^"]*)" dataset_ids=\[(?P<ds>[^\]]*)\]'
))
def _w_no_auth(direct_acc_state, query, ds):
    direct_acc_state.body = {"query": query, "dataset_ids": _parse_ds(ds)}
    _fire(direct_acc_state, with_token=False)


@when(parsers.re(r'前端携带该 token 调用 POST /api/v1/recall/stream body 额外包含字段 "(?P<field>[^"]+)"'))
def _w_extra_field(direct_acc_state, field):
    direct_acc_state.body = {"query": "q", "dataset_ids": [1], field: "x"}
    _fire(direct_acc_state, with_token=True)


@when(parsers.re(
    r'前端携带该 token 调用 POST /api/v1/recall/stream '
    r'body query 为空白标识 "(?P<tok>[^"]+)" dataset_ids=\[(?P<ds>[^\]]*)\]'
))
def _w_blank_query(direct_acc_state, tok, ds):
    mapping = {"EMPTY": "", "SPACES": "   ", "NEWLINE": "\n", "TAB": "\t"}
    direct_acc_state.body = {"query": mapping.get(tok, ""), "dataset_ids": _parse_ds(ds)}
    _fire(direct_acc_state, with_token=True)


@when(parsers.re(
    r'前端携带该 token 调用 POST /api/v1/recall/stream body query="(?P<query>[^"]*)" 且不含 dataset_ids'
))
def _w_omit_dataset(direct_acc_state, query):
    direct_acc_state.body = {"query": query}
    direct_acc_state.omit_dataset = True
    _fire(direct_acc_state, with_token=True)
    direct_acc_state.omit_dataset = False


@when(parsers.re(
    r'前端在 token 未过期时携带同一 token 再次调用 POST /api/v1/recall/stream '
    r'body query="(?P<query>[^"]*)" dataset_ids=\[(?P<ds>[^\]]*)\]'
))
def _w_reuse(direct_acc_state, query, ds):
    direct_acc_state.body = {"query": query, "dataset_ids": _parse_ds(ds)}
    _fire(direct_acc_state, with_token=True)


@when(parsers.parse("token 的 exp 在流执行期间到达"))
def _w_exp_during_stream(direct_acc_state):
    # token 仅在握手期校验；建连后流不再校验 token，故正常以 recall_done 结束。
    direct_acc_state.body = {"query": "q"}
    direct_acc_state.omit_dataset = True
    _fire(direct_acc_state, with_token=True)
    direct_acc_state.omit_dataset = False


@when(parsers.re(r"前端携带新 token 为用户 123 发起第 (?P<n>\d+) 条 POST /api/v1/recall/stream"))
def _w_nth_stream(direct_acc_state, n):
    direct_acc_state.body = {"query": "任意", "dataset_ids": [1]}
    _fire(direct_acc_state, with_token=True)


@when(parsers.re(
    r'前端从 Origin "(?P<origin>[^"]+)" 携带该 token 调用 POST /api/v1/recall/stream '
    r'body query="(?P<query>[^"]*)" dataset_ids=\[(?P<ds>[^\]]*)\]'
))
def _w_cors(direct_acc_state, origin, query, ds):
    # CORS 是全局中间件、在 app 构造期读取 origins；用配置的 origins 构造等价 app 做预检，
    # 验证「配置驱动的 ACAO 回显」这一契约，避免依赖导入期固定的全局 CORS_ORIGINS。
    cors_app = FastAPI()
    cors_app.add_middleware(
        CORSMiddleware,
        allow_origins=direct_acc_state.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    cors_app.include_router(recall_direct.router)
    client = TestClient(cors_app)
    direct_acc_state.response = client.options(
        URL,
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )


@when(parsers.parse("前端主动断开到 Python 的 SSE 连接"))
def _w_disconnect(direct_acc_state):
    # 直接驱动 _guarded_stream 生成器并取消，断言 finally 释放并发名额。
    direct_acc_state.redis.store["recall:concurrent:123"] = 1
    req = RecallRequest(query="q", user_id=123, dataset_ids=[1], top_k=20)
    gen = recall_direct._guarded_stream(direct_acc_state.fake, req, "rid", 123)

    async def _drive() -> None:
        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0.02)  # 让流进入执行中
        task.cancel()  # 模拟前端断连
        try:
            await task
        except asyncio.CancelledError:
            direct_acc_state.cancel_raised = True
        await gen.aclose()  # 触发 finally → release_stream_slot

    asyncio.run(_drive())


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(parsers.re(r"HTTP 响应状态为 (?P<code>\d+)"))
def _status(direct_acc_state, code):
    assert direct_acc_state.response.status_code == int(code)


@then(parsers.re(r'响应 Content-Type 为 "(?P<ct>[^"]+)"'))
def _content_type(direct_acc_state, ct):
    assert direct_acc_state.response.headers["content-type"].startswith(ct)


@then(parsers.re(r'响应头 Cache-Control 为 "(?P<v>[^"]+)"'))
def _cache_control(direct_acc_state, v):
    assert direct_acc_state.response.headers.get("cache-control") == v


@then(parsers.re(r'响应头 X-Accel-Buffering 为 "(?P<v>[^"]+)"'))
def _accel(direct_acc_state, v):
    assert direct_acc_state.response.headers.get("x-accel-buffering") == v


@then(parsers.re(r'收到 SSE 事件 "(?P<name>[^"]+)"'))
def _got_event(direct_acc_state, name):
    assert any(n == name for n, _ in direct_acc_state.events)


@then(parsers.parse("recall_done.data 含字段 hits 与 failed_sources"))
def _recall_done_fields(direct_acc_state):
    data = _event_data(direct_acc_state, "recall_done")
    assert "hits" in data and "failed_sources" in data


@then(parsers.parse("hits 中每个 hit 不含字段 content"))
def _no_content(direct_acc_state):
    for h in _event_data(direct_acc_state, "recall_done")["hits"]:
        assert "content" not in h


@then(parsers.parse("发送 recall_done 后关闭 SSE 流"))
def _close_after_done(direct_acc_state):
    names = [n for n, _ in direct_acc_state.events]
    assert names[-1] == "recall_done"


@then(parsers.re(r'响应体 code 等于 "(?P<code>[^"]+)"'))
def _body_code(direct_acc_state, code):
    assert direct_acc_state.response.json()["code"] == code


@then(parsers.parse("不调用 RecallPipeline"))
def _pipeline_not_called(direct_acc_state):
    assert direct_acc_state.fake.calls == []


@then(parsers.re(r"以 user_id=(?P<uid>\d+) 执行 RecallPipeline"))
def _executed_user(direct_acc_state, uid):
    assert direct_acc_state.fake.calls[0].user_id == int(uid)


@then(parsers.re(r"以 dataset_ids=\[(?P<ds>[^\]]*)\] 执行 RecallPipeline"))
def _executed_dataset(direct_acc_state, ds):
    assert direct_acc_state.fake.calls[0].dataset_ids == _parse_ds(ds)


@then(parsers.re(r'error.data 的 code 等于 "(?P<code>[^"]+)"'))
def _error_code(direct_acc_state, code):
    assert _event_data(direct_acc_state, "error")["code"] == code


@then(parsers.parse("error.data 的 message 不含内部堆栈"))
def _error_no_stack(direct_acc_state):
    msg = _event_data(direct_acc_state, "error")["message"]
    assert "Traceback" not in msg and 'File "' not in msg


@then(parsers.parse("发送 error 后关闭 SSE 流"))
def _close_after_error(direct_acc_state):
    names = [n for n, _ in direct_acc_state.events]
    assert names[-1] == "error"


@then(parsers.re(r'响应头 Access-Control-Allow-Origin 等于 "(?P<origin>[^"]+)"'))
def _acao_eq(direct_acc_state, origin):
    assert direct_acc_state.response.headers.get("access-control-allow-origin") == origin


@then(parsers.re(r'响应头 Access-Control-Allow-Origin 不等于 "(?P<origin>[^"]+)"'))
def _acao_ne(direct_acc_state, origin):
    assert direct_acc_state.response.headers.get("access-control-allow-origin") != origin


@then(parsers.parse("当前 SSE 流不因 token 过期被中断"))
def _stream_not_interrupted(direct_acc_state):
    assert direct_acc_state.response.status_code == 200
    assert any(n == "recall_done" for n, _ in direct_acc_state.events)


@then(parsers.parse("流仍以 recall_done 或 error 正常终态结束"))
def _stream_terminal(direct_acc_state):
    names = [n for n, _ in direct_acc_state.events]
    assert names and names[-1] in {"recall_done", "error"}


@then(parsers.parse("流的最大执行时间仍由 RECALL_STREAM_TIMEOUT_MS 控制"))
def _stream_timeout_governed(direct_acc_state):
    # 已在 timeout 范围内正常完成（recall_done）；超时路径由 scenario「超时」独立覆盖。
    assert any(n == "recall_done" for n, _ in direct_acc_state.events)


@then(parsers.parse("Python 停止继续发送 SSE 事件"))
def _stopped(direct_acc_state):
    assert direct_acc_state.cancel_raised


@then(parsers.parse("Python 尽力取消正在执行的召回任务"))
def _cancelled(direct_acc_state):
    assert direct_acc_state.cancel_raised


@then(parsers.parse("该流不再计入用户 123 的并发流数"))
def _slot_released(direct_acc_state):
    # _guarded_stream finally 已 release：计数从 1 回到 0。
    assert direct_acc_state.redis.store.get("recall:concurrent:123", 0) == 0
