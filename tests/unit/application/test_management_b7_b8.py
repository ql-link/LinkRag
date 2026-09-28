"""B7/B8 的账本、授权和运行配置回归。"""

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import BigInteger, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from src.api.management_auth import require_login, require_role
from src.api.routes import admin_operations as admin_routes
from src.application import admin_operations, usage_ledger
from src.models.db_models import UsageLogDB
from src.services import usage_reporter


@compiles(BigInteger, "sqlite")
def _bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


@pytest.mark.asyncio
async def test_usage_direct_write_and_five_query_shapes(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(UsageLogDB.metadata.create_all, tables=[UsageLogDB.__table__])
        factory = async_sessionmaker(engine, expire_on_commit=False)

        @asynccontextmanager
        async def transaction():
            async with factory() as db:
                async with db.begin():
                    yield db

        monkeypatch.setattr(usage_reporter, "write_transaction", transaction)
        await usage_reporter.report_usage(user_id=7, config_id=9, provider_type="openai",
                                          model_name="m", stage="chat", operation="generate",
                                          prompt_tokens=4, completion_tokens=2, total_tokens=6,
                                          latency_ms=100)
        async with factory() as db:
            date_today = datetime.now(admin_operations._SHANGHAI).date()
            summary = await usage_ledger.summary(db, 7, date_today, date_today, "chat")
            assert summary["totalCalls"] == 1 and summary["totalTokens"] == 6
            assert summary["successRate"] == 1.0
            assert (await usage_ledger.daily(db, 7, date_today, date_today, "chat"))[0]["calls"] == 1
            assert (await usage_ledger.logs(db, 7, date_today, date_today, "chat", 1, 20))["total"] == 1
            assert (await usage_ledger.by_model(db, 7, date_today, date_today))[0]["totalTokens"] == 6
            assert (await usage_ledger.trend(db, 7, date_today, date_today))["previousTokens"] == 0
            assert (await usage_ledger.summary(db, 8, date_today, date_today, "all"))["totalCalls"] == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_admin_dashboard_distinct_period_users():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE sys_user (id INTEGER, role TEXT, status INTEGER, created_at DATETIME)"))
            await connection.execute(text("CREATE TABLE user_login_event (user_id INTEGER, created_at DATETIME)"))
            now = datetime.now(admin_operations._SHANGHAI).replace(tzinfo=None)
            await connection.execute(text("INSERT INTO sys_user VALUES (1,'USER',1,:at),(2,'ADMIN',1,:at)"), {"at": now})
            await connection.execute(text("INSERT INTO user_login_event VALUES (1,:at),(1,:at)"), {"at": now})
        factory = async_sessionmaker(engine)
        async with factory() as db:
            result = await admin_operations.user_dashboard(db, 7)
            assert result["totalUsers"] == 2
            assert result["activeUsers"]["current"] == 1
            assert result["newUsers"]["current"] == 2
            assert len(result["trend"]) == 7
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_admin_only_and_upload_config_failure_keeps_snapshot(monkeypatch):
    app = FastAPI()
    app.include_router(admin_routes.router)
    app.dependency_overrides[require_login] = lambda: SimpleNamespace(user_id=7, role="USER")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/admin/logs/labels")).status_code == 403
    admin_dependency = require_role("ADMIN")
    # The route stores the dependency callable in its graph; override the exact object.
    for route in app.routes:
        for dependency in getattr(route, "dependant", SimpleNamespace(dependencies=[])).dependencies:
            if dependency.call.__name__ == "dependency":
                admin_dependency = dependency.call
    app.dependency_overrides[admin_dependency] = lambda: SimpleNamespace(user_id=7, role="ADMIN")
    monkeypatch.setattr(admin_routes.settings, "B8_DOCUMENT_CONFIG_WRITES_ENABLED", True)

    async def failing_set(*_args, **_kwargs):
        raise RuntimeError("redis unavailable")

    async def ready(*_args, **_kwargs):
        return True

    monkeypatch.setattr(admin_operations.redis_client, "set", failing_set)
    monkeypatch.setattr(admin_operations.redis_client, "set_if_absent", ready)
    old = admin_operations.upload_config._last_valid
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put("/api/v1/admin/document-file-config",
                                    json={"maxSizeBytes": 1024, "allowedSuffixes": ["md"]})
        assert response.status_code == 503
    assert admin_operations.upload_config._last_valid == old


@pytest.mark.asyncio
async def test_loki_rejects_logql_injection_without_calling_backend(monkeypatch):
    with pytest.raises(Exception) as exc:
        await admin_operations.query_logs('x"} |= "secret', None, None, None,
                                          None, None, 1, 50)
    assert getattr(exc.value, "http_status", None) == 400


@pytest.mark.asyncio
async def test_upload_config_success_updates_shared_snapshot(monkeypatch):
    values = {}

    async def saved_set(key, value):
        values[key] = value
        return True

    monkeypatch.setattr(admin_operations.redis_client, "set", saved_set)
    monkeypatch.setattr(admin_operations.redis_client, "set_if_absent", saved_set)
    old = admin_operations.upload_config._last_valid
    try:
        result = await admin_operations.update_upload_config(7, 4096, ["MD", "md", "pdf"])
        assert result["allowedSuffixes"] == ["md", "pdf"]
        assert admin_operations.upload_config._last_valid.max_size_bytes == 4096
        assert '"updatedBy": 7' in values[admin_operations.upload_config._KEY]
    finally:
        admin_operations.upload_config._last_valid = old


@pytest.mark.asyncio
async def test_upload_config_rejects_mixed_instance_defaults(monkeypatch):
    async def existing_key(*_args, **_kwargs):
        return False

    async def other_fingerprint(*_args, **_kwargs):
        return '"different-defaults"'

    async def must_not_write(*_args, **_kwargs):
        raise AssertionError("must not replace shared config")

    monkeypatch.setattr(admin_operations.redis_client, "set_if_absent", existing_key)
    monkeypatch.setattr(admin_operations.redis_client, "get", other_fingerprint)
    monkeypatch.setattr(admin_operations.redis_client, "set", must_not_write)
    with pytest.raises(Exception) as exc:
        await admin_operations.update_upload_config(7, 4096, ["md"])
    assert getattr(exc.value, "code", None) == 50003


@pytest.mark.asyncio
async def test_loki_proxy_sorts_and_redacts(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"result": [{"stream": {"service": "tolink-rag"},
                                         "values": [["1000000000", "older"],
                                                    ["2000000000", json.dumps({"message": "token=abc", "level": "ERROR"})]]}]}}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, *, params=None):
            assert params["query"].startswith('{service="tolink-rag"')
            return Response()

    monkeypatch.setattr(admin_operations.httpx, "AsyncClient", Client)
    result = await admin_operations.query_logs("tolink-rag", "ERROR", None, None,
                                               None, None, 1, 50)
    assert result["total"] == 2
    assert result["items"][0]["message"] == "token=***"
