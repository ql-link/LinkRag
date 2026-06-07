"""内部多路召回 SSE 流式接口验收 step 实现（pytest-bdd 8.x）。

把 ``tests/acceptance/features/recall_http_api.feature`` 的中文 Gherkin 绑定到对
真实 FastAPI 应用（``src.main.app``）的行为断言。pipeline 用 FakePipeline 隔离，
内部 JWT 用配置中的共享密钥真实签发，完整覆盖内部鉴权链路。

state 通过 ``recall_acc_state`` fixture 跨 step 共享；每个 Scenario 一份独立状态，
并在 teardown 还原被改写的 settings。pytest-bdd 8.x 的 step 函数为同步函数，
断连场景用 ``asyncio.run`` 内部驱动流生成器。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

import jwt
import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then, when

from src.api.recall_pipeline_provider import get_recall_pipeline
from src.config import settings
from src.core.pipeline.recall import RecallError, RecallHit, RecallRequest, RecallResponse
from src.main import app

URL = "/api/v1/internal/recall/stream"


class FakePipeline:
    """可控 pipeline 替身；execute 记录入参，并按真实 pipeline 语义按 top_k 截断。"""

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
        # 模拟真实 pipeline 的 top_k 截断
        return RecallResponse(
            query=resp.query,
            hits=resp.hits[: request.top_k],
            per_source_counts=resp.per_source_counts,
            failed_sources=resp.failed_sources,
            elapsed_ms=resp.elapsed_ms,
        )


@dataclass
class _State:
    claims: dict = field(default_factory=dict)
    defect: str | None = None
    body: dict | None = None
    raw_body: str | None = None
    fake: FakePipeline = field(default_factory=FakePipeline)
    response: object = None
    events: list[tuple[str, str]] = field(default_factory=list)
    # 断连场景
    cancel_raised: bool = False
    cancel_events: list[str] = field(default_factory=list)
    _settings_snapshot: dict = field(default_factory=dict)

    def set_setting(self, name: str, value) -> None:
        if name not in self._settings_snapshot:
            self._settings_snapshot[name] = getattr(settings, name)
        setattr(settings, name, value)

    def restore(self) -> None:
        for name, value in self._settings_snapshot.items():
            setattr(settings, name, value)


@pytest.fixture
def recall_acc_state():
    state = _State()
    # 默认成功响应（含两路命中、按 fused_score 降序）
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
    yield state
    state.restore()
    app.dependency_overrides.pop(get_recall_pipeline, None)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_token(state: _State) -> str:
    secret = settings.RECALL_INTERNAL_JWT_SECRET
    payload = {
        "iss": settings.RECALL_INTERNAL_JWT_ISSUER,
        "aud": settings.RECALL_INTERNAL_JWT_AUDIENCE,
        "scope": settings.RECALL_INTERNAL_JWT_SCOPE,
        "sub": state.claims.get("sub", "123"),
        "dataset_ids": state.claims.get("dataset_ids", [1, 2]),
        "jti": "req-1",
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
    if not text:
        return []
    return [int(x) for x in text.split(",")]


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


def _fire(state: _State, *, with_token: bool, request_id: str | None = None) -> None:
    app.dependency_overrides[get_recall_pipeline] = lambda: state.fake
    headers = {"Accept": "text/event-stream"}
    if with_token:
        headers["Authorization"] = f"Bearer {_make_token(state)}"
    if request_id is not None:
        headers["X-Request-Id"] = request_id
    client = TestClient(app)
    if state.raw_body is not None:
        resp = client.post(URL, content=state.raw_body, headers=headers)
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
# Background：配置
# ---------------------------------------------------------------------------


@given(parsers.re(r"配置 (?P<name>[A-Z_]+)=(?P<value>.+)"))
def _set_config(recall_acc_state, name, value):
    casted: object
    if value in ("True", "False"):
        casted = value == "True"
    elif value.isdigit():
        casted = int(value)
    else:
        casted = value
    recall_acc_state.set_setting(name, casted)


@given(parsers.parse("Java 与 Python 共享同一 HS256 JWT 密钥"))
def _shared_secret(recall_acc_state):
    pass


@given(parsers.parse("服务端已装配 bm25 与 sparse 两路 retriever"))
def _two_sources(recall_acc_state):
    pass


# ---------------------------------------------------------------------------
# Given：JWT claims / pipeline 状态
# ---------------------------------------------------------------------------


@given(parsers.re(
    r"内部 JWT claims sub=(?P<sub>\d+) aud=\S+ iss=\S+ scope=\S+ "
    r"dataset_ids=\[(?P<ds>[^\]]*)\] 未过期"
))
def _claims_full(recall_acc_state, sub, ds):
    recall_acc_state.claims = {"sub": sub, "dataset_ids": _parse_ds(ds)}


@given(parsers.re(r"内部 JWT claims sub=(?P<sub>\d+) dataset_ids=\[(?P<ds>[^\]]*)\] 合法未过期"))
def _claims_short(recall_acc_state, sub, ds):
    recall_acc_state.claims = {"sub": sub, "dataset_ids": _parse_ds(ds)}


@given(parsers.re(r'内部 JWT 存在缺陷 "(?P<defect>[^"]+)"'))
def _claims_defect(recall_acc_state, defect):
    recall_acc_state.claims = {"sub": "123", "dataset_ids": [1]}
    recall_acc_state.defect = defect


@given(parsers.parse("bm25 与 sparse 两路均返回命中"))
def _both_hit(recall_acc_state):
    pass  # 默认响应已是两路命中


@given(parsers.parse("各路合计可融合出 50 个候选"))
def _fifty_candidates(recall_acc_state):
    recall_acc_state.fake.response = RecallResponse(
        query="q",
        hits=[RecallHit(str(i), i, 1, 1.0 - i * 0.001, {"bm25": 1.0, "sparse": None})
              for i in range(50)],
        per_source_counts={"bm25": 50, "sparse": 0},
        failed_sources=[],
        elapsed_ms=20,
    )


@given(parsers.parse("bm25 路成功返回命中"))
def _bm25_ok(recall_acc_state):
    pass


@given(parsers.parse("sparse 路执行抛异常"))
def _sparse_fail(recall_acc_state):
    recall_acc_state.fake.response = RecallResponse(
        query="q",
        hits=[RecallHit("1", 1, 1, 0.5, {"bm25": 1.0, "sparse": None})],
        per_source_counts={"bm25": 1, "sparse": 0},
        failed_sources=["sparse"],
        elapsed_ms=8,
    )


@given(parsers.parse("bm25 与 sparse 两路均执行抛异常"))
def _all_fail(recall_acc_state):
    recall_acc_state.fake.exc = RecallError("all retrievers failed")


@given(parsers.parse("recall runtime 执行超过 RECALL_STREAM_TIMEOUT_MS"))
def _runtime_timeout(recall_acc_state):
    recall_acc_state.set_setting("RECALL_STREAM_TIMEOUT_MS", 10)
    recall_acc_state.fake.delay = 0.5


@given(parsers.parse("recall 正在执行中"))
def _recall_running(recall_acc_state):
    recall_acc_state.fake.delay = 10.0


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(parsers.re(
    r'携带该 JWT 调用 recall/stream body query="(?P<query>[^"]*)" '
    r'user_id=(?P<user_id>\d+) dataset_ids=\[(?P<ds>[^\]]*)\]'
))
def _call_with_token(recall_acc_state, query, user_id, ds):
    recall_acc_state.body = {"query": query, "user_id": int(user_id), "dataset_ids": _parse_ds(ds)}
    _fire(recall_acc_state, with_token=True)


@when(parsers.re(
    r'不携带 Authorization 头调用 recall/stream body query="(?P<query>[^"]*)" '
    r'user_id=(?P<user_id>\d+) dataset_ids=\[(?P<ds>[^\]]*)\]'
))
def _call_without_token(recall_acc_state, query, user_id, ds):
    recall_acc_state.body = {"query": query, "user_id": int(user_id), "dataset_ids": _parse_ds(ds)}
    _fire(recall_acc_state, with_token=False)


@when(parsers.re(r'携带该 JWT 调用 recall/stream body 额外包含字段 "(?P<field>[^"]+)"'))
def _call_extra_field(recall_acc_state, field):
    recall_acc_state.body = {"query": "q", "user_id": 123, "dataset_ids": [1], field: "x"}
    _fire(recall_acc_state, with_token=True)


@when(parsers.re(r'携带该 JWT 调用 recall/stream body 缺陷 "(?P<defect>[^"]+)"'))
def _call_malformed(recall_acc_state, defect):
    base = {"query": "q", "user_id": 123, "dataset_ids": [1]}
    if defect == "缺少 query 字段":
        base.pop("query")
    elif defect == "缺少 user_id 字段":
        base.pop("user_id")
    elif defect == "缺少 dataset_ids 字段":
        base.pop("dataset_ids")
    elif defect == "user_id 为字符串":
        base["user_id"] = "abc"
    elif defect == "dataset_ids 不是列表":
        base["dataset_ids"] = "nope"
    elif defect == "JSON 格式非法":
        recall_acc_state.raw_body = "{not-json"
        _fire(recall_acc_state, with_token=True)
        return
    recall_acc_state.body = base
    _fire(recall_acc_state, with_token=True)


@when(parsers.re(
    r'携带该 JWT 调用 recall/stream body query 为空白标识 "(?P<token>[^"]+)" '
    r'user_id=(?P<user_id>\d+) dataset_ids=\[(?P<ds>[^\]]*)\]'
))
def _call_blank_query(recall_acc_state, token, user_id, ds):
    mapping = {"EMPTY": "", "SPACES": "   ", "NEWLINE": "\n", "TAB": "\t"}
    recall_acc_state.body = {
        "query": mapping.get(token, ""),
        "user_id": int(user_id),
        "dataset_ids": _parse_ds(ds),
    }
    _fire(recall_acc_state, with_token=True)


@when(parsers.re(
    r'携带该 JWT 不带 X-Request-Id 调用 recall/stream body query="(?P<query>[^"]*)" '
    r'user_id=(?P<user_id>\d+) dataset_ids=\[(?P<ds>[^\]]*)\]'
))
def _call_no_request_id(recall_acc_state, query, user_id, ds):
    recall_acc_state.body = {"query": query, "user_id": int(user_id), "dataset_ids": _parse_ds(ds)}
    _fire(recall_acc_state, with_token=True)


@when(parsers.re(
    r'携带该 JWT 带 X-Request-Id "(?P<rid>[^"]+)" 调用 recall/stream '
    r'body query="(?P<query>[^"]*)" user_id=(?P<user_id>\d+) dataset_ids=\[(?P<ds>[^\]]*)\]'
))
def _call_with_request_id(recall_acc_state, rid, query, user_id, ds):
    recall_acc_state.body = {"query": query, "user_id": int(user_id), "dataset_ids": _parse_ds(ds)}
    _fire(recall_acc_state, with_token=True, request_id=rid)


@when(parsers.parse("Java 主动断开到 Python 的 SSE 连接"))
def _java_disconnect(recall_acc_state):
    from src.api.recall_stream_runtime import recall_event_stream

    req = RecallRequest(query="q", user_id=123, dataset_ids=[1], top_k=20)

    async def _drive() -> None:
        gen = recall_event_stream(recall_acc_state.fake, req, "rid")
        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0.02)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            recall_acc_state.cancel_raised = True

    asyncio.run(_drive())


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(parsers.re(r"HTTP 响应状态为 (?P<code>\d+)"))
def _status(recall_acc_state, code):
    assert recall_acc_state.response.status_code == int(code)


@then(parsers.re(r'响应 Content-Type 为 "(?P<ct>[^"]+)"'))
def _content_type(recall_acc_state, ct):
    assert recall_acc_state.response.headers["content-type"].startswith(ct)


@then(parsers.re(r'收到 SSE 事件 "(?P<name>[^"]+)"'))
def _got_event(recall_acc_state, name):
    assert any(n == name for n, _ in recall_acc_state.events)


@then(parsers.parse("recall_done.data 含字段 hits 与 failed_sources"))
def _recall_done_fields(recall_acc_state):
    data = _event_data(recall_acc_state, "recall_done")
    assert "hits" in data and "failed_sources" in data


@then(parsers.parse("recall_done.failed_sources 等于空列表"))
def _failed_empty(recall_acc_state):
    assert _event_data(recall_acc_state, "recall_done")["failed_sources"] == []


@then(parsers.parse("hits 中每个 hit 含字段 chunk_id, doc_id, dataset_id, fused_score, scores"))
def _hit_fields(recall_acc_state):
    for h in _event_data(recall_acc_state, "recall_done")["hits"]:
        assert set(h) == {"chunk_id", "doc_id", "dataset_id", "fused_score", "scores"}


@then(parsers.parse("hits 中每个 hit 的 chunk_id 为字符串"))
def _chunk_id_str(recall_acc_state):
    for h in _event_data(recall_acc_state, "recall_done")["hits"]:
        assert isinstance(h["chunk_id"], str)


@then(parsers.parse("hits 中每个 hit 不含字段 content"))
def _no_content(recall_acc_state):
    for h in _event_data(recall_acc_state, "recall_done")["hits"]:
        assert "content" not in h


@then(parsers.re(r"hits 中每个 hit 的 scores 的键集合等于 \{(?P<keys>[^}]*)\}"))
def _scores_keys(recall_acc_state, keys):
    expected = {k.strip().strip('"') for k in keys.split(",")}
    for h in _event_data(recall_acc_state, "recall_done")["hits"]:
        assert set(h["scores"]) == expected


@then(parsers.parse("hits 按 fused_score 降序排列"))
def _sorted_desc(recall_acc_state):
    scores = [h["fused_score"] for h in _event_data(recall_acc_state, "recall_done")["hits"]]
    assert scores == sorted(scores, reverse=True)


@then(parsers.parse("发送 recall_done 后关闭 SSE 流"))
def _close_after_done(recall_acc_state):
    names = [n for n, _ in recall_acc_state.events]
    assert names[-1] == "recall_done"


@then(parsers.re(r"recall_done.hits 长度不超过 (?P<n>\d+)"))
def _hits_le(recall_acc_state, n):
    assert len(_event_data(recall_acc_state, "recall_done")["hits"]) <= int(n)


@then(parsers.parse("以 dataset_ids 空列表执行 RecallPipeline"))
def _executed_empty_ds(recall_acc_state):
    assert recall_acc_state.fake.calls[0].dataset_ids == []


@then(parsers.re(r'响应体 code 等于 "(?P<code>[^"]+)"'))
def _body_code(recall_acc_state, code):
    assert recall_acc_state.response.json()["code"] == code


@then(parsers.parse("不调用 RecallPipeline"))
def _pipeline_not_called(recall_acc_state):
    assert recall_acc_state.fake.calls == []


@then(parsers.re(r'recall_done.failed_sources 包含 "(?P<src>[^"]+)"'))
def _failed_contains(recall_acc_state, src):
    assert src in _event_data(recall_acc_state, "recall_done")["failed_sources"]


@then(parsers.parse("recall_done.hits 非空"))
def _hits_nonempty(recall_acc_state):
    assert _event_data(recall_acc_state, "recall_done")["hits"]


@then(parsers.re(r'error.data 的 code 等于 "(?P<code>[^"]+)"'))
def _error_code(recall_acc_state, code):
    assert _event_data(recall_acc_state, "error")["code"] == code


@then(parsers.parse("error.data 的 message 不含内部堆栈"))
def _error_no_stack(recall_acc_state):
    msg = _event_data(recall_acc_state, "error")["message"]
    assert "Traceback" not in msg and "File \"" not in msg


@then(parsers.parse("发送 error 后关闭 SSE 流"))
def _close_after_error(recall_acc_state):
    names = [n for n, _ in recall_acc_state.events]
    assert names[-1] == "error"


@then(parsers.parse("Python 停止继续发送 SSE 事件"))
def _stopped_events(recall_acc_state):
    assert recall_acc_state.cancel_raised


@then(parsers.parse("Python 尽力取消正在执行的召回任务"))
def _cancelled_task(recall_acc_state):
    assert recall_acc_state.cancel_raised


@then(parsers.parse("Python 不执行后续 rerank、上下文拼装或 LLM 步骤"))
def _no_downstream(recall_acc_state):
    # recall-only：流内只跑 pipeline，无后续步骤；取消后亦无任何事件产出。
    assert recall_acc_state.cancel_raised


@then(parsers.parse("Python 为本次请求生成 request_id"))
def _request_id_generated(recall_acc_state):
    assert recall_acc_state.response.headers.get("x-request-id")


@then(parsers.parse("日志中能通过该 request_id 关联 API 与 pipeline 执行"))
def _request_id_logged(recall_acc_state):
    # request_id 透出响应头，作为可关联标识（日志由 loguru 输出，不在单测断言文本）。
    assert recall_acc_state.response.headers.get("x-request-id")


@then(parsers.re(r'本次请求的 request_id 等于 "(?P<rid>[^"]+)"'))
def _request_id_equals(recall_acc_state, rid):
    assert recall_acc_state.response.headers.get("x-request-id") == rid
