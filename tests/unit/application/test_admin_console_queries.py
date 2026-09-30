"""管理台补充查询：用户列表筛选 / 统计、用户详情、总览计数。"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.management_http import BusinessError
from src.application import admin_operations, identity_users

_SCHEMA = [
    "CREATE TABLE sys_user (id INTEGER PRIMARY KEY, username TEXT, nickname TEXT, email TEXT, phone TEXT, avatar_url TEXT, role TEXT, status INTEGER, bio TEXT, team TEXT, last_login_at DATETIME, created_at DATETIME)",
    "CREATE TABLE user_login_event (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, login_source TEXT, created_at DATETIME)",
    "CREATE TABLE dataset (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, status TEXT, is_deleted INTEGER DEFAULT 0, updated_at DATETIME)",
    "CREATE TABLE document_original_file (id INTEGER PRIMARY KEY, dataset_id INTEGER, user_id INTEGER, file_size INTEGER, is_deleted INTEGER DEFAULT 0)",
    "CREATE TABLE chat_conversation (id INTEGER PRIMARY KEY, user_id INTEGER, created_at DATETIME)",
    "CREATE TABLE llm_usage_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, created_at DATETIME)",
    "CREATE TABLE llm_system_provider (id INTEGER PRIMARY KEY, provider_type TEXT, provider_name TEXT)",
    "CREATE TABLE llm_provider_model (id INTEGER PRIMARY KEY, is_active INTEGER)",
    "CREATE TABLE llm_model_config (id INTEGER PRIMARY KEY, scope TEXT, owner_user_id INTEGER, provider_id INTEGER, provider_type TEXT)",
    "CREATE TABLE blog_post (id INTEGER PRIMARY KEY, status TEXT, is_deleted INTEGER DEFAULT 0, updated_at DATETIME)",
    "CREATE TABLE user_feedback (id INTEGER PRIMARY KEY, status TEXT)",
]


@pytest.fixture
async def db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    now = datetime.now(admin_operations._SHANGHAI).replace(tzinfo=None)
    old = now - timedelta(days=60)
    async with engine.begin() as conn:
        for ddl in _SCHEMA:
            await conn.execute(text(ddl))
        await conn.execute(
            text(
                "INSERT INTO sys_user VALUES "
                "(10001,'linxiao','林晓','linxiao@acme.cn',NULL,NULL,'USER',1,NULL,NULL,:now,:now),"
                "(10002,'zhou','周明远','zhou@linkrag.cn',NULL,NULL,'ADMIN',1,NULL,NULL,NULL,:old),"
                "(10003,'sun','孙浩','sun@qq.com',NULL,NULL,'USER',0,NULL,NULL,NULL,:old)"
            ),
            {"now": now, "old": old},
        )
        # 与 0044 一致：存量行经列默认值归为 tolink；再放入一个接入应用影子用户，
        # 验证默认列表 / 看板 / 总览都不计入它。
        await conn.execute(
            text("ALTER TABLE sys_user ADD COLUMN app_code TEXT NOT NULL DEFAULT 'tolink'")
        )
        await conn.execute(
            text(
                "INSERT INTO sys_user (id,username,nickname,role,status,created_at,app_code) "
                "VALUES (10009,'linkresume_abc','linkresume 用户','USER',1,:now,'linkresume')"
            ),
            {"now": now},
        )
        await conn.execute(
            text(
                "INSERT INTO dataset VALUES (1,10001,'产品知识库','ACTIVE',0,:now),(2,10001,'旧库','ACTIVE',1,:now),"
                "(3,10002,'技术文档','ACTIVE',0,:now)"
            ),
            {"now": now},
        )
        await conn.execute(
            text("INSERT INTO document_original_file VALUES (1,1,10001,1000,0),(2,1,10001,500,0),(3,2,10001,9,1)")
        )
        await conn.execute(text("INSERT INTO chat_conversation VALUES (1,10001,:now),(2,10001,:old)"), {"now": now, "old": old})
        await conn.execute(
            text(
                "INSERT INTO llm_usage_log (user_id,prompt_tokens,completion_tokens,total_tokens,created_at) VALUES "
                "(10001,100,20,120,:now),(10001,1000,1000,2000,:old)"
            ),
            {"now": now, "old": old},
        )
        await conn.execute(text("INSERT INTO llm_system_provider VALUES (1,'openai','OpenAI')"))
        await conn.execute(text("INSERT INTO llm_provider_model VALUES (1,1),(2,0)"))
        await conn.execute(
            text("INSERT INTO llm_model_config VALUES (1,'USER',10001,1,'openai'),(2,'SYSTEM',0,1,'linkrag')")
        )
        await conn.execute(
            text("INSERT INTO blog_post VALUES (1,'PUBLISHED',0,:now),(2,'DRAFT',0,:old),(3,'DRAFT',1,:now)"),
            {"now": now, "old": old},
        )
        await conn.execute(text("INSERT INTO user_feedback VALUES (1,'PENDING'),(2,'RESOLVED')"))
        await conn.execute(
            text("INSERT INTO user_login_event (user_id,login_source,created_at) VALUES (10001,'LOGIN',:now)"),
            {"now": now},
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def ctx():
        async with factory() as session:
            yield session

    monkeypatch.setattr(identity_users, "get_db_context", ctx)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_search_users_filters_and_stats(db):
    page = await identity_users.search_users(1, 10)
    assert page["total"] == 3
    first = next(u for u in page["items"] if u["id"] == 10001)
    assert first["datasetCount"] == 1  # 软删知识库不计
    assert first["tokens30d"] == 120  # 仅近 30 天
    assert first["lastLoginAt"]
    assert (await identity_users.search_users(1, 10, keyword="林"))["total"] == 1
    assert (await identity_users.search_users(1, 10, keyword="#10002"))["items"][0]["username"] == "zhou"
    assert (await identity_users.search_users(1, 10, role="ADMIN"))["total"] == 1
    assert (await identity_users.search_users(1, 10, status=0))["items"][0]["username"] == "sun"
    by_login = await identity_users.search_users(1, 10, sort="lastLogin")
    assert by_login["items"][0]["id"] == 10001  # 从未登录排在后面
    # 默认只含 tolink 用户（上面 total==3 已排除影子用户）；按 appCode 可单独查看影子用户。
    shadow = await identity_users.search_users(1, 10, app_code="linkresume")
    assert shadow["total"] == 1
    assert shadow["items"][0]["id"] == 10009
    assert shadow["items"][0]["appCode"] == "linkresume"
    assert first["appCode"] == "tolink"


@pytest.mark.asyncio
async def test_user_detail_aggregates(db):
    detail = await identity_users.user_detail(10001)
    stats = detail["stats"]
    assert stats["datasetCount"] == 1 and stats["fileCount"] == 2 and stats["fileBytes"] == 1500
    assert stats["conversationCount"] == 2 and stats["conversations30d"] == 1
    assert stats["tokens30d"] == 120 and stats["promptTokens30d"] == 100
    assert stats["modelConfigCount"] == 1 and stats["modelProviders"] == ["OpenAI"]
    assert detail["datasets"][0]["name"] == "产品知识库"
    assert detail["recentLogins"][0]["source"] == "LOGIN"
    with pytest.raises(BusinessError) as missing:
        await identity_users.user_detail(1)
    assert missing.value.code == 20001


@pytest.mark.asyncio
async def test_overview_counts_without_sync_tables(db):
    async with db() as session:
        result = await admin_operations.overview(session)
    assert result["users"]["total"] == 3
    assert result["users"]["active7d"]["current"] == 1
    assert result["models"] == {"providers": 1, "activeProviderModels": 1, "platformConfigs": 1}
    assert result["blog"] == {"published": 1, "drafts": 1, "staleDrafts": 1}
    assert result["feedback"]["pending"] == 1
    assert result["sync"] is None  # 同步表未迁移时降级为 null


@pytest.mark.asyncio
async def test_login_audit_records_ip_ua_and_failures(db, monkeypatch):
    """0043：成功登录记录 IP / UA，密码错误与禁用写入失败表；详情按时间合并展示。"""
    async with db() as session:
        await session.execute(text("ALTER TABLE user_login_event ADD COLUMN ip TEXT"))
        await session.execute(text("ALTER TABLE user_login_event ADD COLUMN user_agent TEXT"))
        await session.execute(
            text(
                "CREATE TABLE user_login_failure (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, reason TEXT, ip TEXT, user_agent TEXT, created_at DATETIME)"
            )
        )
        await session.commit()

    @asynccontextmanager
    async def write_ctx():
        async with db() as session:
            async with session.begin():
                yield session

    monkeypatch.setattr(identity_users, "write_transaction", write_ctx)
    ctx = identity_users.LoginContext("116.228.1.2", "Mozilla/5.0 Chrome/129 Macintosh")
    await identity_users._record_login(10001, "LOGIN", ctx)
    await identity_users._record_failure(10001, "BAD_PASSWORD", ctx)
    logins = (await identity_users.user_detail(10001))["recentLogins"]
    assert {(r["success"], r["ip"]) for r in logins if r["ip"]} == {(True, "116.228.1.2"), (False, "116.228.1.2")}
    assert any(r["reason"] == "BAD_PASSWORD" for r in logins)
    assert identity_users.LoginContext("x" * 100, "y" * 400).ip == "x" * 64


@pytest.mark.asyncio
async def test_login_event_falls_back_without_0043_columns(db, monkeypatch):
    """0043 未执行：成功事件仍落库（旧列集合），失败表缺失时静默跳过。"""

    @asynccontextmanager
    async def write_ctx():
        async with db() as session:
            async with session.begin():
                yield session

    monkeypatch.setattr(identity_users, "write_transaction", write_ctx)
    await identity_users._record_login(10002, "LOGIN", identity_users.LoginContext("1.1.1.1", "ua"))
    await identity_users._record_failure(10002, "BAD_PASSWORD", identity_users.LoginContext())
    logins = (await identity_users.user_detail(10002))["recentLogins"]
    assert [r["success"] for r in logins] == [True]
