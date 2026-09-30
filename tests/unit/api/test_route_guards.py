"""内部服务令牌、调试开关与 LLM 调用路由的 HTTP 层鉴权行为。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from src.api.java_access_auth import AuthContext, require_admin, verify_user_token
from src.api.routes import internal, llm, mq, parse
from src.application.recall_errors import RecallApiError
from src.config import settings
from src.database import get_db


def _client(app: FastAPI) -> httpx.AsyncClient:
    @app.exception_handler(RecallApiError)
    async def _recall_error(_request, exc: RecallApiError):  # 与 src.main 行为一致
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.status_code, content={"code": exc.code})

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.fixture
def internal_app(monkeypatch):
    app = FastAPI()
    app.include_router(internal.router)
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    reader = AsyncMock()
    reader.get_system_providers.return_value = []
    monkeypatch.setattr(internal, "LLMCatalogReader", lambda _db: reader)
    return app


@pytest.mark.asyncio
async def test_internal_llm_rejects_when_token_not_configured(
    internal_app, monkeypatch
):
    monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", None)
    async with _client(internal_app) as client:
        response = await client.get(
            "/api/v1/internal/llm/providers", headers={"Authorization": "Bearer "}
        )
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header", [None, "Bearer wrong", "svc-token", "Basic svc-token"]
)
async def test_internal_llm_rejects_bad_token(internal_app, monkeypatch, header):
    monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", "svc-token")
    headers = {"Authorization": header} if header else {}
    async with _client(internal_app) as client:
        response = await client.get("/api/v1/internal/llm/providers", headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_internal_llm_accepts_configured_token(internal_app, monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", "svc-token")
    async with _client(internal_app) as client:
        response = await client.get(
            "/api/v1/internal/llm/providers",
            headers={"Authorization": "Bearer svc-token"},
        )
    assert response.status_code == 200
    assert response.json()["data"] == {"items": []}


@pytest.fixture
def debug_app():
    app = FastAPI()
    app.include_router(mq.router)
    app.include_router(parse.router)
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/mq/vendor/info", "/api/v1/mq/send/raw"])
async def test_debug_routes_hidden_when_switch_off(debug_app, monkeypatch, path):
    monkeypatch.setattr(settings, "DEBUG_ENDPOINTS_ENABLED", False)
    # 即便是管理员，开关关闭时也按不存在处理。
    debug_app.dependency_overrides[require_admin] = lambda: AuthContext(
        1, "r", role="ADMIN"
    )
    async with _client(debug_app) as client:
        method = client.get if path.endswith("info") else client.post
        response = await method(path)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_debug_routes_require_login_when_switch_on(debug_app, monkeypatch):
    monkeypatch.setattr(settings, "DEBUG_ENDPOINTS_ENABLED", True)
    async with _client(debug_app) as client:
        response = await client.get("/api/v1/mq/vendor/info")
        submit = await client.post("/api/v1/parser/task/submit", json={})
    assert response.status_code == 401
    assert submit.status_code == 401


@pytest.mark.asyncio
async def test_debug_routes_reject_non_admin(debug_app, monkeypatch):
    monkeypatch.setattr(settings, "DEBUG_ENDPOINTS_ENABLED", True)
    debug_app.dependency_overrides[verify_user_token] = lambda: AuthContext(
        7, "r", role="USER"
    )
    async with _client(debug_app) as client:
        response = await client.get("/api/v1/mq/vendor/info")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_debug_routes_allow_admin_when_switch_on(debug_app, monkeypatch):
    monkeypatch.setattr(settings, "DEBUG_ENDPOINTS_ENABLED", True)
    debug_app.dependency_overrides[verify_user_token] = lambda: AuthContext(
        1, "r", role="ADMIN"
    )
    async with _client(debug_app) as client:
        response = await client.get("/api/v1/mq/vendor/info")
    assert response.status_code == 200
    assert response.json()["current_vendor"] == settings.MQ_VENDOR


@pytest.fixture
def llm_app():
    app = FastAPI()
    app.include_router(llm.router)
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    return app


@pytest.mark.asyncio
async def test_llm_routes_require_access_token(llm_app):
    async with _client(llm_app) as client:
        # 旧调用方式：仅凭 X-User-Id 自报身份，现已拒绝。
        response = await client.post(
            "/api/v1/llm/embed",
            headers={"X-User-Id": "1"},
            json={"config_id": 1, "input": "x"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_llm_routes_use_token_identity_not_header(llm_app, monkeypatch):
    captured = {}
    provider = AsyncMock()
    provider.embed.return_value = type(
        "R", (), {"model_dump": lambda self: {"ok": True}}
    )()

    async def _resolve(db, user_id, capability, *, config_id):
        captured["user_id"] = user_id
        return provider

    monkeypatch.setattr(llm, "_resolve_provider", _resolve)
    llm_app.dependency_overrides[verify_user_token] = lambda: AuthContext(42, "r")
    async with _client(llm_app) as client:
        response = await client.post(
            "/api/v1/llm/embed",
            headers={"X-User-Id": "999"},
            json={"config_id": 1, "input": "x"},
        )
    assert response.status_code == 200
    assert captured["user_id"] == 42
