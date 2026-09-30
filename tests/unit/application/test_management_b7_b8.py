"""B7/B8 的账本、授权和运行配置回归。"""

import json
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import BigInteger, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from src.api.management_auth import require_login
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
        await usage_reporter.report_usage(
            user_id=7,
            config_id=9,
            provider_type="openai",
            model_name="m",
            stage="chat",
            operation="generate",
            prompt_tokens=4,
            completion_tokens=2,
            total_tokens=6,
            latency_ms=100,
        )
        async with factory() as db:
            date_today = datetime.now(admin_operations._SHANGHAI).date()
            summary = await usage_ledger.summary(db, 7, date_today, date_today, "chat")
            assert summary["totalCalls"] == 1 and summary["totalTokens"] == 6
            assert summary["successRate"] == 1.0
            assert (await usage_ledger.daily(db, 7, date_today, date_today, "chat"))[0][
                "calls"
            ] == 1
            assert (await usage_ledger.logs(db, 7, date_today, date_today, "chat", 1, 20))[
                "total"
            ] == 1
            assert (await usage_ledger.by_model(db, 7, date_today, date_today))[0][
                "totalTokens"
            ] == 6
            assert (await usage_ledger.trend(db, 7, date_today, date_today))["previousTokens"] == 0
            assert (await usage_ledger.summary(db, 8, date_today, date_today, "all"))[
                "totalCalls"
            ] == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_admin_dashboard_distinct_period_users():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE sys_user (id INTEGER, role TEXT, status INTEGER, created_at DATETIME)"
                )
            )
            await connection.execute(
                text("CREATE TABLE user_login_event (user_id INTEGER, created_at DATETIME)")
            )
            now = datetime.now(admin_operations._SHANGHAI).replace(tzinfo=None)
            await connection.execute(
                text("INSERT INTO sys_user VALUES (1,'USER',1,:at),(2,'ADMIN',1,:at)"), {"at": now}
            )
            # 与 0044 一致：存量行经列默认值归为 tolink。
            await connection.execute(
                text("ALTER TABLE sys_user ADD COLUMN app_code TEXT NOT NULL DEFAULT 'tolink'")
            )
            await connection.execute(
                text("INSERT INTO user_login_event VALUES (1,:at),(1,:at)"), {"at": now}
            )
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
    # require_role 的闭包依赖 require_login，改为 ADMIN 身份即可通过角色校验，
    # 不依赖 FastAPI 内部路由结构（0.140 起 include_router 惰性展开，app.routes 取不到 dependant）。
    app.dependency_overrides[require_login] = lambda: SimpleNamespace(user_id=7, role="ADMIN")
    monkeypatch.setattr(admin_routes.settings, "B8_DOCUMENT_CONFIG_WRITES_ENABLED", True)

    async def failing_set(*_args, **_kwargs):
        raise RuntimeError("redis unavailable")

    async def ready(*_args, **_kwargs):
        return True

    monkeypatch.setattr(admin_operations.redis_client, "set", failing_set)
    monkeypatch.setattr(admin_operations.redis_client, "set_if_absent", ready)
    old = admin_operations.upload_config._last_valid
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            "/api/v1/admin/document-file-config",
            json={"maxSizeBytes": 1024, "allowedSuffixes": ["md"]},
        )
        assert response.status_code == 503
    assert admin_operations.upload_config._last_valid == old


@pytest.mark.asyncio
async def test_loki_rejects_logql_injection_without_calling_backend(monkeypatch):
    with pytest.raises(Exception) as exc:
        await admin_operations.query_logs('x"} |= "secret', None, None, None, None, None, 1, 50)
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
async def test_upload_config_read_preserves_shared_java_suffix_order(monkeypatch):
    async def current_limits():
        return admin_operations.upload_config.DocumentUploadLimits(
            frozenset({"md", "pdf", "docx"}), 4096
        )

    async def redis_get(key):
        assert key == admin_operations.upload_config._KEY
        return json.dumps(
            {
                "maxSizeBytes": 4096,
                "allowedSuffixes": ["md", "pdf", "docx"],
                "updatedBy": 7,
                "updatedAt": "2026-09-29T10:00:00",
            }
        )

    monkeypatch.setattr(admin_operations.upload_config, "current_limits", current_limits)
    monkeypatch.setattr(admin_operations.redis_client, "get", redis_get)
    assert (await admin_operations.get_upload_config())["allowedSuffixes"] == ["md", "pdf", "docx"]


@pytest.mark.asyncio
async def test_upload_config_default_preserves_declared_suffix_order(monkeypatch):
    async def current_limits():
        return admin_operations.upload_config.DocumentUploadLimits()

    async def redis_get(_key):
        return None

    monkeypatch.setattr(admin_operations.upload_config, "current_limits", current_limits)
    monkeypatch.setattr(admin_operations.redis_client, "get", redis_get)
    assert (await admin_operations.get_upload_config())["allowedSuffixes"] == list(
        admin_operations.upload_config._DEFAULT_SUFFIX_ORDER
    )


@pytest.mark.asyncio
async def test_loki_proxy_sorts_and_redacts(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "result": [
                        {
                            "stream": {"service": "tolink-rag"},
                            "values": [
                                ["1000000000", "older"],
                                [
                                    "2000000000",
                                    json.dumps({"message": "token=abc", "level": "ERROR"}),
                                ],
                            ],
                        }
                    ]
                }
            }

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, *, params=None):
            assert params["query"].startswith(
                ('{service="tolink-rag"', '{service_name="tolink-rag"')
            )
            return (
                Response()
                if params["query"].startswith('{service="')
                else SimpleNamespace(
                    raise_for_status=lambda: None, json=lambda: {"data": {"result": []}}
                )
            )

    monkeypatch.setattr(admin_operations.httpx, "AsyncClient", Client)
    result = await admin_operations.query_logs("tolink-rag", "ERROR", None, None, None, None, 1, 50)
    assert result["total"] == 2
    assert result["items"][0]["message"] == "token=******"


def test_loki_entry_matches_java_loguru_and_access_contract():
    line = json.dumps(
        {
            "record": {
                "time": {"repr": "2026-09-29 10:00:00+08:00"},
                "level": {"name": "INFO"},
                "extra": {"pid": 17, "traceId": "trace-1", "loggerName": "ACCESS"},
                "message": "password=secret-value",
                "process": {"id": 99},
            }
        }
    )
    entry = admin_operations._entry("1000000000", line, {"service": "tolink-rag"})
    assert entry["time"] == "2026-09-29 10:00:00+08:00"
    assert entry["level"] == "ACCESS"
    assert entry["pid"] == "17"
    assert entry["trace_id"] == "trace-1"
    assert entry["message"] == "password=******"
    java = admin_operations._entry(
        "1000000000", json.dumps({"loggerName": "AUDIT", "stackTrace": "token=abc"}), {}
    )
    assert java["level"] == "AUDIT"
    assert java["exception"] == "token=******"


@pytest.mark.asyncio
async def test_loki_historical_service_name_streams_remain_queryable(monkeypatch):
    class Response:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": self.data}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, *, params=None):
            if url.endswith("/query_range"):
                if params["query"].startswith('{service_name="tolink-service"'):
                    return Response(
                        {
                            "result": [
                                {
                                    "stream": {"service_name": "tolink-service"},
                                    "values": [["1000000000", "legacy log"]],
                                }
                            ]
                        }
                    )
                return Response({"result": []})
            return Response(["tolink-service"] if "/service_name/" in url else ["linkresume"])

    monkeypatch.setattr(admin_operations.httpx, "AsyncClient", lambda **kwargs: Client())
    result = await admin_operations.query_logs(
        "tolink-service", None, None, None, None, None, 1, 50
    )
    assert result["total"] == 1
    assert result["items"][0]["service"] == "tolink-service"
    assert (await admin_operations.log_labels())["services"] == ["linkresume", "tolink-service"]


@pytest.mark.asyncio
async def test_loki_malformed_success_payload_is_bounded(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": {
                    "result": [
                        {
                            "stream": "malformed",
                            "values": [None, ["1000000000"], ["1000000000", "plain"]],
                        }
                    ]
                }
            }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(admin_operations.httpx, "AsyncClient", lambda **kwargs: Client())
    result = await admin_operations.query_logs(None, None, None, None, None, None, 1, 50)
    assert result["total"] == 1
    assert result["items"][0]["message"] == "plain"


@pytest.mark.asyncio
async def test_loki_bad_labels_payload_uses_fallback(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": "malformed"}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(admin_operations.httpx, "AsyncClient", lambda **kwargs: Client())
    assert (await admin_operations.log_labels())["services"] == ["tolink-service", "tolink-rag"]
