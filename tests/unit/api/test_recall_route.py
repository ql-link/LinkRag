"""内部多路召回 SSE 路由端到端单测（FastAPI TestClient）。

覆盖 .specs/recall-http-api/acceptance.feature 的握手前鉴权/参数/scope 场景，以及
建流后的 SSE 终态事件（recall_done / error / 超时）。pipeline 用 FakePipeline 隔离，
JWT 用配置中的共享密钥真实签发，验证内部鉴权链路。
"""

from __future__ import annotations

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from src.api.recall_pipeline_provider import get_recall_pipeline
from src.config import settings
from src.core.pipeline.recall import (
    RecallError,
    RecallHit,
    RecallResponse,
)
from src.main import app


# ---------------------------------------------------------------------------
# 桩件 + 辅助
# ---------------------------------------------------------------------------


class FakePipeline:
    """记录 execute 入参的可控 pipeline 替身。"""

    def __init__(self, response: RecallResponse | None = None, exc: Exception | None = None,
                 delay: float = 0.0) -> None:
        self._response = response
        self._exc = exc
        self._delay = delay
        self.calls: list = []

    async def execute(self, request):
        import asyncio
        self.calls.append(request)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._exc is not None:
            raise self._exc
        return self._response


def _ok_response() -> RecallResponse:
    return RecallResponse(
        query="q",
        hits=[
            RecallHit(chunk_id="1001", doc_id=10, dataset_id=1, fused_score=0.92,
                      scores={"bm25": 8.7, "sparse": 0.76}),
            RecallHit(chunk_id="1002", doc_id=11, dataset_id=1, fused_score=0.40,
                      scores={"bm25": 5.0, "sparse": None}),
        ],
        per_source_counts={"bm25": 2, "sparse": 1},
        failed_sources=[],
        elapsed_ms=12,
    )


def make_token(**overrides) -> str:
    secret = overrides.pop("__secret__", settings.RECALL_INTERNAL_JWT_SECRET)
    payload = {
        "iss": settings.RECALL_INTERNAL_JWT_ISSUER,
        "aud": settings.RECALL_INTERNAL_JWT_AUDIENCE,
        "scope": settings.RECALL_INTERNAL_JWT_SCOPE,
        "sub": "123",
        "dataset_ids": [1, 2],
        "jti": "req-1",
        "exp": int(time.time()) + 300,
    }
    payload.update(overrides)
    return jwt.encode(payload, secret, algorithm="HS256")


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


@pytest.fixture
def fake_pipeline():
    fake = FakePipeline(response=_ok_response())
    app.dependency_overrides[get_recall_pipeline] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_recall_pipeline, None)


@pytest.fixture
def client():
    return TestClient(app)


URL = "/api/v1/internal/recall/stream"


def _post(client, token: str | None, body: dict | str, extra_headers: dict | None = None):
    headers = {"Accept": "text/event-stream"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
    if isinstance(body, str):
        return client.post(URL, content=body, headers=headers)
    return client.post(URL, json=body, headers=headers)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def test_valid_credential_returns_recall_done(client, fake_pipeline):
    resp = _post(client, make_token(), {"query": "数据治理", "user_id": 123, "dataset_ids": [1, 2]})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    assert len(events) == 1
    name, data = events[0]
    assert name == "recall_done"
    import json
    payload = json.loads(data)
    assert payload["failed_sources"] == []
    first = payload["hits"][0]
    assert set(first) == {"chunk_id", "doc_id", "dataset_id", "fused_score", "scores"}
    assert isinstance(first["chunk_id"], str)
    assert "content" not in first
    # 降序
    scores = [h["fused_score"] for h in payload["hits"]]
    assert scores == sorted(scores, reverse=True)


def test_request_carries_user_id_from_claims_and_config_top_k(client, fake_pipeline):
    _post(client, make_token(sub="123"), {"query": "q", "user_id": 123, "dataset_ids": [1]})
    req = fake_pipeline.calls[0]
    assert req.user_id == 123
    assert req.top_k == settings.RECALL_RESULT_LIMIT
    assert req.dataset_ids == [1]


def test_claims_empty_dataset_ids_allows_full_scope(client, fake_pipeline):
    token = make_token(dataset_ids=[])
    resp = _post(client, token, {"query": "q", "user_id": 123, "dataset_ids": []})
    assert resp.status_code == 200
    assert _parse_sse(resp.text)[0][0] == "recall_done"
    assert fake_pipeline.calls[0].dataset_ids == []


# ---------------------------------------------------------------------------
# 鉴权（握手前 → 非 2xx JSON，不调用 pipeline）
# ---------------------------------------------------------------------------


def test_missing_credential_returns_401(client, fake_pipeline):
    resp = _post(client, None, {"query": "q", "user_id": 123, "dataset_ids": [1]})
    assert resp.status_code == 401
    assert resp.json()["code"] == "RECALL_INTERNAL_UNAUTHORIZED"
    assert fake_pipeline.calls == []


@pytest.mark.parametrize("token", [
    make_token(__secret__="wrong-secret"),         # 签名不匹配
    make_token(iss="evil"),                         # iss 错误
    make_token(aud="someone-else"),                 # aud 错误
    make_token(scope="other:scope"),                # scope 错误
    make_token(exp=int(time.time()) - 10),          # 已过期
])
def test_invalid_jwt_returns_401(client, fake_pipeline, token):
    resp = _post(client, token, {"query": "q", "user_id": 123, "dataset_ids": [1]})
    assert resp.status_code == 401
    assert resp.json()["code"] == "RECALL_INTERNAL_UNAUTHORIZED"
    assert fake_pipeline.calls == []


def test_user_id_mismatch_returns_403(client, fake_pipeline):
    resp = _post(client, make_token(sub="123"), {"query": "q", "user_id": 999, "dataset_ids": [1]})
    assert resp.status_code == 403
    assert resp.json()["code"] == "RECALL_USER_MISMATCH"
    assert fake_pipeline.calls == []


def test_dataset_scope_forbidden_returns_403(client, fake_pipeline):
    resp = _post(client, make_token(dataset_ids=[1, 2]),
                 {"query": "q", "user_id": 123, "dataset_ids": [1, 3]})
    assert resp.status_code == 403
    assert resp.json()["code"] == "RECALL_SCOPE_FORBIDDEN"
    assert fake_pipeline.calls == []


def test_dataset_subset_is_allowed(client, fake_pipeline):
    resp = _post(client, make_token(dataset_ids=[1, 2]),
                 {"query": "q", "user_id": 123, "dataset_ids": [1]})
    assert resp.status_code == 200
    assert _parse_sse(resp.text)[0][0] == "recall_done"


# ---------------------------------------------------------------------------
# 请求体校验
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["top_k", "sources", "strict", "include_content", "doc_ids"])
def test_non_first_version_field_returns_422(client, fake_pipeline, field):
    body = {"query": "q", "user_id": 123, "dataset_ids": [1], field: "x"}
    resp = _post(client, make_token(), body)
    assert resp.status_code == 422
    assert resp.json()["code"] == "RECALL_INVALID_REQUEST"
    assert fake_pipeline.calls == []


@pytest.mark.parametrize("body", [
    {"user_id": 123, "dataset_ids": [1]},                       # 缺 query
    {"query": "q", "dataset_ids": [1]},                          # 缺 user_id
    {"query": "q", "user_id": 123},                              # 缺 dataset_ids
    {"query": "q", "user_id": "abc", "dataset_ids": [1]},       # user_id 类型错
    {"query": "q", "user_id": 123, "dataset_ids": "nope"},      # dataset_ids 非列表
])
def test_malformed_body_returns_422(client, fake_pipeline, body):
    resp = _post(client, make_token(), body)
    assert resp.status_code == 422
    assert resp.json()["code"] == "RECALL_INVALID_REQUEST"
    assert fake_pipeline.calls == []


def test_invalid_json_returns_422(client, fake_pipeline):
    resp = _post(client, make_token(), "{not-json")
    assert resp.status_code == 422
    assert resp.json()["code"] == "RECALL_INVALID_REQUEST"
    assert fake_pipeline.calls == []


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_blank_query_returns_400(client, fake_pipeline, query):
    resp = _post(client, make_token(), {"query": query, "user_id": 123, "dataset_ids": [1]})
    assert resp.status_code == 400
    assert resp.json()["code"] == "RECALL_INVALID_REQUEST"
    assert fake_pipeline.calls == []


# ---------------------------------------------------------------------------
# 降级 / 失败终态（建流后 → SSE）
# ---------------------------------------------------------------------------


def test_partial_failure_reports_degraded_recall_done(client):
    degraded = RecallResponse(
        query="q",
        hits=[RecallHit(chunk_id="1", doc_id=1, dataset_id=1, fused_score=0.5,
                        scores={"bm25": 1.0, "sparse": None})],
        per_source_counts={"bm25": 1, "sparse": 0},
        failed_sources=["sparse"],
        elapsed_ms=5,
    )
    fake = FakePipeline(response=degraded)
    app.dependency_overrides[get_recall_pipeline] = lambda: fake
    try:
        resp = _post(TestClient(app), make_token(), {"query": "q", "user_id": 123, "dataset_ids": [1]})
        import json
        name, data = _parse_sse(resp.text)[0]
        assert name == "recall_done"
        payload = json.loads(data)
        assert payload["failed_sources"] == ["sparse"]
        assert payload["hits"]
    finally:
        app.dependency_overrides.pop(get_recall_pipeline, None)


def test_all_sources_failed_emits_sse_error(client):
    fake = FakePipeline(exc=RecallError("all retrievers failed"))
    app.dependency_overrides[get_recall_pipeline] = lambda: fake
    try:
        resp = _post(TestClient(app), make_token(), {"query": "q", "user_id": 123, "dataset_ids": [1]})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        import json
        name, data = _parse_sse(resp.text)[0]
        assert name == "error"
        payload = json.loads(data)
        assert payload["code"] == "RECALL_ALL_SOURCES_FAILED"
        assert "Traceback" not in payload["message"]
    finally:
        app.dependency_overrides.pop(get_recall_pipeline, None)


def test_timeout_emits_sse_error(client, monkeypatch):
    monkeypatch.setattr(settings, "RECALL_STREAM_TIMEOUT_MS", 10)
    fake = FakePipeline(response=_ok_response(), delay=0.5)
    app.dependency_overrides[get_recall_pipeline] = lambda: fake
    try:
        resp = _post(TestClient(app), make_token(), {"query": "q", "user_id": 123, "dataset_ids": [1]})
        import json
        name, data = _parse_sse(resp.text)[0]
        assert name == "error"
        assert json.loads(data)["code"] == "RECALL_TIMEOUT"
    finally:
        app.dependency_overrides.pop(get_recall_pipeline, None)


# ---------------------------------------------------------------------------
# 请求追踪
# ---------------------------------------------------------------------------


def test_request_id_propagated_when_supplied(client, fake_pipeline):
    resp = _post(client, make_token(), {"query": "q", "user_id": 123, "dataset_ids": [1]},
                 extra_headers={"X-Request-Id": "req-abc"})
    assert resp.headers.get("x-request-id") == "req-abc"


def test_request_id_generated_when_absent(client, fake_pipeline):
    resp = _post(client, make_token(), {"query": "q", "user_id": 123, "dataset_ids": [1]})
    assert resp.headers.get("x-request-id")


# ---------------------------------------------------------------------------
# 断连取消（直接驱动流生成器）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_disconnect_cancels_and_emits_no_event():
    import asyncio

    from src.api.routes.recall import _recall_event_stream
    from src.core.pipeline.recall import RecallRequest

    fake = FakePipeline(response=_ok_response(), delay=10.0)
    req = RecallRequest(query="q", user_id=1, dataset_ids=[1], top_k=20)
    gen = _recall_event_stream(fake, req, "rid")

    task = asyncio.ensure_future(gen.__anext__())
    await asyncio.sleep(0.02)  # 让流进入执行中
    task.cancel()  # 模拟客户端断连

    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake.calls  # pipeline 已被触发，但因取消未产出任何事件
