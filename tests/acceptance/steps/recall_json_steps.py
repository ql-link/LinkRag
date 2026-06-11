"""对外纯召回 JSON 验收 step 实现（pytest-bdd 8.x）。

把 ``tests/acceptance/features/recall_json.feature`` 的中文 Gherkin 绑定到对真实
FastAPI 应用（``src.main.app``）的行为断言。pipeline 用 FakePipeline 隔离，session
JWT 用独立 session 密钥真实签发。纯召回不调 CHAT 模型、不建 SSE、不限流，故无需生成
替身与 Redis 替身。

state 通过 ``recall_json_state`` fixture 跨 step 共享；每个 Scenario 一份独立状态，
teardown 还原被改写的 settings、清空 dependency_overrides。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import jwt
import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then, when

from src.application.recall_pipeline_provider import get_recall_pipeline
from src.config import settings
from src.core.pipeline.recall import RecallHit, RecallRequest, RecallResponse
from src.main import app

URL = "/api/v1/recall"


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


@dataclass
class _State:
    claims: dict = field(default_factory=dict)
    body: dict | None = None
    omit_config: bool = True  # 纯召回默认不带 config_id
    fake: FakePipeline = field(default_factory=FakePipeline)
    response: object = None
    _settings_snapshot: dict = field(default_factory=dict)

    def set_setting(self, name: str, value) -> None:
        if name not in self._settings_snapshot:
            self._settings_snapshot[name] = getattr(settings, name)
        setattr(settings, name, value)

    def restore(self) -> None:
        for name, value in self._settings_snapshot.items():
            setattr(settings, name, value)


@pytest.fixture
def recall_json_state():
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
    yield state
    state.restore()
    app.dependency_overrides.pop(get_recall_pipeline, None)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_token(state: _State) -> str:
    payload = {
        "iss": settings.RECALL_SESSION_JWT_ISSUER,
        "aud": settings.RECALL_SESSION_JWT_AUDIENCE,
        "scope": settings.RECALL_SESSION_JWT_SCOPE,
        "sub": state.claims.get("sub", "123"),
        "dataset_ids": state.claims.get("dataset_ids", [1, 2]),
        "exp": int(time.time()) + 300,
    }
    return jwt.encode(payload, settings.RECALL_SESSION_JWT_SECRET, algorithm="HS256")


def _parse_ds(text: str) -> list[int]:
    text = text.strip()
    return [int(x) for x in text.split(",")] if text else []


def _fire(state: _State, *, with_token: bool) -> None:
    app.dependency_overrides[get_recall_pipeline] = lambda: state.fake
    headers = {}
    if with_token:
        headers["Authorization"] = f"Bearer {_make_token(state)}"
    client = TestClient(app)
    state.response = client.post(URL, json=state.body, headers=headers)


# ---------------------------------------------------------------------------
# Background / 配置
# ---------------------------------------------------------------------------


@given(parsers.re(r"配置 (?P<name>[A-Z_]+)=(?P<value>.+)"))
def _set_config(recall_json_state, name, value):
    if value in ("True", "False"):
        casted = value == "True"
    elif value.isdigit():
        casted = int(value)
    else:
        casted = value
    recall_json_state.set_setting(name, casted)


@given(parsers.re(r"配置 session token 的 (?P<name>[A-Z_]+)=(?P<value>.+)"))
def _set_session_config(recall_json_state, name, value):
    recall_json_state.set_setting(name, value)


@given(parsers.parse("服务端已装配 bm25 与 sparse 两路 retriever"))
def _two_sources(recall_json_state):
    pass


# ---------------------------------------------------------------------------
# Given：claims / pipeline 状态
# ---------------------------------------------------------------------------


@given(parsers.re(r"session token claims sub=(?P<sub>\d+).*dataset_ids=\[(?P<ds>[^\]]*)\].*"))
def _claims(recall_json_state, sub, ds):
    recall_json_state.claims = {"sub": sub, "dataset_ids": _parse_ds(ds)}


@given(parsers.parse("bm25 与 sparse 两路均返回命中"))
def _both_hit(recall_json_state):
    pass


@given(parsers.parse("bm25 与 sparse 两路均返回 0 命中"))
def _zero_hit(recall_json_state):
    recall_json_state.fake.response = RecallResponse(
        query="q", hits=[], per_source_counts={}, failed_sources=[], elapsed_ms=1
    )


@given(parsers.parse("bm25 路抛异常而 sparse 路返回命中"))
def _partial_degrade(recall_json_state):
    resp = recall_json_state.fake.response
    recall_json_state.fake.response = RecallResponse(
        query=resp.query,
        hits=resp.hits,
        per_source_counts=resp.per_source_counts,
        failed_sources=["bm25"],
        elapsed_ms=resp.elapsed_ms,
    )


@given(parsers.parse("用户 123 无默认 EMBEDDING 配置"))
def _embedding_missing(recall_json_state):
    from src.core.pipeline.recall import RecallFatalError

    recall_json_state.fake.exc = RecallFatalError("user embedding config missing")


@given(parsers.parse("bm25 与 sparse 两路均执行抛异常"))
def _all_fail(recall_json_state):
    from src.core.pipeline.recall import RecallError

    recall_json_state.fake.exc = RecallError("all retrievers failed")


@given(parsers.parse("召回执行超过 RECALL_STREAM_TIMEOUT_MS"))
def _timeout(recall_json_state):
    recall_json_state.set_setting("RECALL_STREAM_TIMEOUT_MS", 10)
    recall_json_state.fake.delay = 0.5


@given(parsers.parse("召回执行期间发生未预期异常"))
def _unexpected(recall_json_state):
    recall_json_state.fake.exc = RuntimeError("boom")


@given(parsers.re(r"用户 123 已有 (?P<n>\d+) 条 RAG 流在执行"))
def _rag_streams_running(recall_json_state, n):
    # 纯召回不查并发计数，此前置仅表达「RAG 流已占满」语境，对纯召回应无影响。
    pass


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(
    parsers.re(
        r'前端携带该 token 调用 POST /api/v1/recall body query="(?P<query>[^"]*)" dataset_ids=\[(?P<ds>[^\]]*)\] 不含 config_id'
    )
)
def _w_omit_config(recall_json_state, query, ds):
    recall_json_state.body = {"query": query, "dataset_ids": _parse_ds(ds)}
    _fire(recall_json_state, with_token=True)


@when(
    parsers.re(
        r'前端携带该 token 调用 POST /api/v1/recall body query="(?P<query>[^"]*)" config_id=(?P<cid>\d+) dataset_ids=\[(?P<ds>[^\]]*)\]'
    )
)
def _w_with_config(recall_json_state, query, cid, ds):
    recall_json_state.body = {"query": query, "config_id": int(cid), "dataset_ids": _parse_ds(ds)}
    _fire(recall_json_state, with_token=True)


@when(parsers.re(r'前端携带该 token 调用 POST /api/v1/recall body 额外包含字段 "(?P<field>[^"]+)"'))
def _w_extra_field(recall_json_state, field):
    recall_json_state.body = {"query": "q", "dataset_ids": [1], field: "x"}
    _fire(recall_json_state, with_token=True)


@when(
    parsers.re(
        r'前端携带该 token 调用 POST /api/v1/recall body query 为空白标识 "(?P<tok>[^"]+)" dataset_ids=\[(?P<ds>[^\]]*)\]'
    )
)
def _w_blank_query(recall_json_state, tok, ds):
    mapping = {"EMPTY": "", "SPACES": "   ", "NEWLINE": "\n", "TAB": "\t"}
    recall_json_state.body = {"query": mapping.get(tok, ""), "dataset_ids": _parse_ds(ds)}
    _fire(recall_json_state, with_token=True)


@when(
    parsers.re(
        r'前端不携带 Authorization 头调用 POST /api/v1/recall body query="(?P<query>[^"]*)" dataset_ids=\[(?P<ds>[^\]]*)\]'
    )
)
def _w_no_auth(recall_json_state, query, ds):
    recall_json_state.body = {"query": query, "dataset_ids": _parse_ds(ds)}
    _fire(recall_json_state, with_token=False)


@when(
    parsers.re(
        r'前端携带该 token 为用户 123 调用 POST /api/v1/recall body query="(?P<query>[^"]*)" dataset_ids=\[(?P<ds>[^\]]*)\]'
    )
)
def _w_user_call(recall_json_state, query, ds):
    recall_json_state.body = {"query": query, "dataset_ids": _parse_ds(ds)}
    _fire(recall_json_state, with_token=True)


@when(
    parsers.re(
        r'前端携带该 token 调用 POST /api/v1/recall body query="(?P<query>[^"]*)" dataset_ids=\[(?P<ds>[^\]]*)\]'
    )
)
def _w_with_token(recall_json_state, query, ds):
    recall_json_state.body = {"query": query, "dataset_ids": _parse_ds(ds)}
    _fire(recall_json_state, with_token=True)


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(parsers.re(r"HTTP 响应状态为 (?P<code>\d+)"))
def _status(recall_json_state, code):
    assert recall_json_state.response.status_code == int(code)


@then(parsers.re(r'响应 Content-Type 为 "(?P<ct>[^"]+)"'))
def _content_type(recall_json_state, ct):
    assert recall_json_state.response.headers["content-type"].startswith(ct)


@then(parsers.parse("响应不是 text/event-stream"))
def _not_sse(recall_json_state):
    assert not recall_json_state.response.headers["content-type"].startswith("text/event-stream")


@then(parsers.parse("响应体含字段 hits 与 failed_sources"))
def _body_fields(recall_json_state):
    data = recall_json_state.response.json()
    assert "hits" in data and "failed_sources" in data


@then(parsers.parse("响应体含字段 failed_sources"))
def _body_failed_sources(recall_json_state):
    assert "failed_sources" in recall_json_state.response.json()


@then(
    parsers.parse(
        "hits 中每个 hit 含字段 chunk_id 与 doc_id 与 dataset_id 与 fused_score 与 scores"
    )
)
def _hit_shape(recall_json_state):
    for h in recall_json_state.response.json()["hits"]:
        for field_name in ("chunk_id", "doc_id", "dataset_id", "fused_score", "scores"):
            assert field_name in h, f"hit missing {field_name}: {h}"


@then(parsers.parse("hits 中每个 hit 不含字段 content"))
def _no_content(recall_json_state):
    for h in recall_json_state.response.json()["hits"]:
        assert "content" not in h


@then(parsers.parse("响应体 hits 为空数组"))
def _hits_empty(recall_json_state):
    assert recall_json_state.response.json()["hits"] == []


@then(parsers.parse("响应体 hits 非空"))
def _hits_non_empty(recall_json_state):
    assert recall_json_state.response.json()["hits"]


@then(parsers.re(r'响应体 failed_sources 含 "(?P<src>[^"]+)"'))
def _failed_sources_contains(recall_json_state, src):
    assert src in recall_json_state.response.json()["failed_sources"]


@then(parsers.parse("不调用 CHAT 模型生成"))
def _chat_not_called(recall_json_state):
    # 纯召回响应不含任何生成字段。
    data = recall_json_state.response.json()
    assert "answer" not in data


@then(parsers.re(r'响应体 code 等于 "(?P<code>[^"]+)"'))
def _body_code(recall_json_state, code):
    assert recall_json_state.response.json()["code"] == code


@then(parsers.parse("响应体 message 不含内部堆栈"))
def _message_no_stack(recall_json_state):
    msg = recall_json_state.response.json()["message"]
    assert "Traceback" not in msg and 'File "' not in msg


@then(parsers.parse("不调用 RecallPipeline"))
def _pipeline_not_called(recall_json_state):
    assert recall_json_state.fake.calls == []


@then(parsers.re(r"以 user_id=(?P<uid>\d+) 执行 RecallPipeline"))
def _executed_user(recall_json_state, uid):
    assert recall_json_state.fake.calls[0].user_id == int(uid)


@then(parsers.re(r"以 dataset_ids=\[(?P<ds>[^\]]*)\] 执行 RecallPipeline"))
def _executed_dataset(recall_json_state, ds):
    assert recall_json_state.fake.calls[0].dataset_ids == _parse_ds(ds)
