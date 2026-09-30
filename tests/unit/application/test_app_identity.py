"""接入应用身份：凭证校验、影子用户映射、运维操作（SQLite 模拟共享 schema）。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import bcrypt
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.application import app_identity
from src.application.app_identity import AppClient, AppIdentityError

_SCHEMA = [
    "CREATE TABLE sys_user (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, "
    "password_hash TEXT NOT NULL, nickname TEXT, email TEXT UNIQUE, role TEXT, status INTEGER, "
    "app_code TEXT NOT NULL DEFAULT 'tolink')",
    "CREATE TABLE app_client (id INTEGER PRIMARY KEY AUTOINCREMENT, app_code TEXT UNIQUE, "
    "client_id TEXT UNIQUE, secret_hash TEXT, status TEXT DEFAULT 'ACTIVE', "
    "default_dense_config_id INTEGER, default_sparse_config_id INTEGER, description TEXT)",
    "CREATE TABLE app_user_binding (id INTEGER PRIMARY KEY AUTOINCREMENT, app_code TEXT, "
    "external_user_id TEXT, user_id INTEGER UNIQUE, default_dataset_id INTEGER, "
    "UNIQUE (app_code, external_user_id))",
    "CREATE TABLE llm_model_config (id INTEGER PRIMARY KEY, scope TEXT, capability TEXT, "
    "is_active INTEGER)",
]


@pytest.fixture
async def factory(monkeypatch, tmp_path):
    # 文件库：每个 session 独立连接，才能真实模拟并发事务（:memory: 共用单连接，
    # 失败方 rollback 会连带回滚赢家未提交的写入）。
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'app_identity.db'}",
        connect_args={"timeout": 5},
    )
    async with engine.begin() as conn:
        for ddl in _SCHEMA:
            await conn.execute(text(ddl))
        await conn.execute(
            text(
                "INSERT INTO llm_model_config VALUES (1,'SYSTEM','EMBEDDING',1),"
                "(2,'SYSTEM','SPARSE_EMBEDDING',1),(3,'USER','EMBEDDING',1),"
                "(4,'SYSTEM','EMBEDDING',0)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO sys_user (username,password_hash,role,status) "
                "VALUES ('tolink-user','x','USER',1)"
            )
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def read_ctx():
        async with session_factory() as session:
            yield session

    @asynccontextmanager
    async def write_ctx():
        async with session_factory() as session:
            async with session.begin():
                yield session

    monkeypatch.setattr(app_identity, "get_db_context", read_ctx)
    monkeypatch.setattr(app_identity, "write_transaction", write_ctx)
    app_identity.credential_cache.clear()
    yield session_factory
    app_identity.credential_cache.clear()
    await engine.dispose()


async def _create(app_code: str = "linkresume") -> str:
    client_id, secret = await app_identity.create_app_client(
        app_code, dense_config_id=1, sparse_config_id=2
    )
    return f"{client_id}.{secret}"


@pytest.mark.asyncio
async def test_create_stores_only_hash_and_verifies_credential(factory):
    token = await _create()
    client_id, secret = token.split(".", 1)
    async with factory() as db:
        stored = (
            await db.execute(
                text("SELECT secret_hash FROM app_client WHERE client_id=:c"),
                {"c": client_id},
            )
        ).scalar_one()
    assert secret not in stored
    assert bcrypt.checkpw(secret.encode(), stored.encode())
    app = await app_identity.verify_app_credential(token)
    assert (
        app.app_code,
        app.default_dense_config_id,
        app.default_sparse_config_id,
    ) == (
        "linkresume",
        1,
        2,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate", ["wrong-secret", "unknown-client", "no-dot", "empty-secret"]
)
async def test_invalid_credentials_rejected(factory, mutate):
    token = await _create()
    client_id, secret = token.split(".", 1)
    bad = {
        "wrong-secret": f"{client_id}.{secret}x",
        "unknown-client": f"app_missing.{secret}",
        "no-dot": client_id + secret,
        "empty-secret": f"{client_id}.",
    }[mutate]
    with pytest.raises(AppIdentityError) as exc:
        await app_identity.verify_app_credential(bad)
    assert (exc.value.status_code, exc.value.code) == (401, "APP_CREDENTIAL_INVALID")


@pytest.mark.asyncio
async def test_disabled_app_rejected_and_rotation_invalidates_old_secret(factory):
    token = await _create()
    await app_identity.set_app_status("linkresume", "DISABLED")
    with pytest.raises(AppIdentityError) as disabled:
        await app_identity.verify_app_credential(token)
    assert (disabled.value.status_code, disabled.value.code) == (403, "APP_DISABLED")
    await app_identity.set_app_status("linkresume", "ACTIVE")
    new_id, new_secret = await app_identity.rotate_app_secret("linkresume")
    app_identity.credential_cache.clear()  # 模拟 60s 缓存过期
    with pytest.raises(AppIdentityError):
        await app_identity.verify_app_credential(token)
    assert (
        await app_identity.verify_app_credential(f"{new_id}.{new_secret}")
    ).app_code == ("linkresume")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dense", "sparse", "reason"),
    [(3, 2, "SYSTEM"), (4, 2, "SYSTEM"), (2, 2, "capability"), (1, 1, "capability")],
)
async def test_create_requires_active_system_configs_with_matching_capability(
    factory, dense, sparse, reason
):
    with pytest.raises(ValueError, match=reason):
        await app_identity.create_app_client(
            "linkresume", dense_config_id=dense, sparse_config_id=sparse
        )


@pytest.mark.parametrize(
    "code", ["tolink", "LinkResume", "a", "1abc", "x" * 33, "bad-code"]
)
def test_app_code_rules(code):
    assert not app_identity.is_valid_app_code(code)


@pytest.mark.parametrize("value", [None, "", "a" * 65, "12 3", "1/2", "中文"])
def test_external_user_id_rules(value):
    with pytest.raises(AppIdentityError) as exc:
        app_identity.validate_external_user_id(value)
    assert exc.value.code == "APP_USER_ID_INVALID"


def test_shadow_username_is_bounded_and_unpredictable():
    names = {app_identity.shadow_username("x" * 32) for _ in range(20)}
    assert len(names) == 20
    assert all(len(name) <= 64 and name.startswith("x" * 32 + "_") for name in names)


def _app(code: str = "linkresume") -> AppClient:
    return AppClient(1, code, "cid", 1, 2)


@pytest.mark.asyncio
async def test_external_user_id_is_case_sensitive(factory):
    """评审 R1：nanoid / base62 外部 ID 大小写不同即为不同用户（生产列为 utf8mb4_bin）。"""

    lower = await app_identity.resolve_shadow_user(_app(), "aB3x")
    upper = await app_identity.resolve_shadow_user(_app(), "Ab3X")
    assert lower.user_id != upper.user_id


@pytest.mark.asyncio
async def test_web_registration_cannot_squat_shadow_username(factory):
    """评审 R2：即便 Web 注册占用了旧的"可推导"用户名，首次映射仍然成功。"""

    import hashlib

    squatted = "linkresume_" + hashlib.sha1(b"123").hexdigest()[:20]
    async with factory() as db:
        async with db.begin():
            await db.execute(
                text(
                    "INSERT INTO sys_user (username,password_hash,role,status) "
                    "VALUES (:u,'x','USER',1)"
                ),
                {"u": squatted},
            )
    user = await app_identity.resolve_shadow_user(_app(), "123")
    async with factory() as db:
        name = (
            await db.execute(
                text("SELECT username FROM sys_user WHERE id=:id"), {"id": user.user_id}
            )
        ).scalar_one()
    assert name != squatted


@pytest.mark.asyncio
async def test_resolve_shadow_user_is_idempotent_and_namespaced(factory):
    first = await app_identity.resolve_shadow_user(_app(), "10086")
    again = await app_identity.resolve_shadow_user(_app(), "10086")
    other_user = await app_identity.resolve_shadow_user(_app(), "10087")
    other_app = await app_identity.resolve_shadow_user(_app("otherapp"), "10086")
    assert first == again
    assert len({first.user_id, other_user.user_id, other_app.user_id}) == 3
    async with factory() as db:
        row = (
            (
                await db.execute(
                    text(
                        "SELECT password_hash,email,app_code,role FROM sys_user WHERE id=:id"
                    ),
                    {"id": first.user_id},
                )
            )
            .mappings()
            .one()
        )
    assert row["app_code"] == "linkresume"
    assert row["email"] is None and row["role"] == "USER"
    assert row["password_hash"] == app_identity.SHADOW_PASSWORD_SENTINEL
    with pytest.raises(ValueError):
        # 哨兵值不是合法 bcrypt 串，任何密码都无法通过校验。
        bcrypt.checkpw(b"anything", row["password_hash"].encode())


@pytest.mark.asyncio
async def test_concurrent_first_access_creates_single_shadow_user(factory, monkeypatch):
    real_create = app_identity._create_shadow_user
    gate = asyncio.Event()
    calls = 0

    async def racing_create(app_code, external_user_id):
        # 两个并发请求都已读到"无绑定"后才开始写，复现首建竞态。
        nonlocal calls
        calls += 1
        if calls == 2:
            gate.set()
        await gate.wait()
        await real_create(app_code, external_user_id)

    monkeypatch.setattr(app_identity, "_create_shadow_user", racing_create)
    results = await asyncio.gather(
        app_identity.resolve_shadow_user(_app(), "42"),
        app_identity.resolve_shadow_user(_app(), "42"),
    )
    assert results[0] == results[1]
    async with factory() as db:
        count = (
            await db.execute(
                text("SELECT COUNT(*) FROM sys_user WHERE app_code='linkresume'")
            )
        ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_disabled_shadow_user_rejected(factory):
    user = await app_identity.resolve_shadow_user(_app(), "7")
    async with factory() as db:
        async with db.begin():
            await db.execute(
                text("UPDATE sys_user SET status=0 WHERE id=:id"), {"id": user.user_id}
            )
    with pytest.raises(AppIdentityError) as exc:
        await app_identity.resolve_shadow_user(_app(), "7")
    assert (exc.value.status_code, exc.value.code) == (403, "APP_USER_DISABLED")


@pytest.mark.asyncio
async def test_binding_pointing_at_foreign_user_fails_closed(factory):
    """人为篡改绑定指向 tolink 用户时拒绝，而不是以该用户身份放行。"""

    async with factory() as db:
        async with db.begin():
            await db.execute(
                text(
                    "INSERT INTO app_user_binding (app_code,external_user_id,user_id) "
                    "VALUES ('linkresume','evil',1)"
                )
            )
    with pytest.raises(AppIdentityError) as exc:
        await app_identity.resolve_shadow_user(_app(), "evil")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_set_default_dataset_updates_only_own_binding(factory):
    user = await app_identity.resolve_shadow_user(_app(), "8")
    await app_identity.set_default_dataset("linkresume", user.user_id, 555)
    assert (
        await app_identity.resolve_shadow_user(_app(), "8")
    ).default_dataset_id == 555
    await app_identity.set_default_dataset("otherapp", user.user_id, 999)
    assert (
        await app_identity.resolve_shadow_user(_app(), "8")
    ).default_dataset_id == 555


@pytest.mark.asyncio
async def test_shadow_user_is_invisible_to_web_auth_lookups(factory, monkeypatch):
    """影子用户即使拿到合法签名的 Web token，两条 Web 鉴权读路径都按不存在处理。"""

    from src.api import management_auth
    from src.core.storage.auth_identity import load_current_user_identity

    app = await app_identity.verify_app_credential(await _create())
    shadow = await app_identity.resolve_shadow_user(app, "42")

    @asynccontextmanager
    async def read_ctx():
        async with factory() as session:
            yield session

    monkeypatch.setattr(management_auth, "get_db_context", read_ctx)
    repo = management_auth.SqlUserAuthorizationRepository()
    async with factory() as session:
        assert await load_current_user_identity(session, shadow.user_id) is None
        # 对照：tolink 存量用户（id=1）照常可见，证明过滤条件不是整体失效。
        assert (await load_current_user_identity(session, 1)).user_id == 1
    assert await repo.get_user(shadow.user_id) is None
    assert (await repo.get_user(1)).user_id == 1
