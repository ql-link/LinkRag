import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import bcrypt
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.management_auth import (
    AccessClaims,
    AccessTokenVerifier,
    ManagementAuthenticator,
    UserAuthorization,
)
from src.api.routes import identity_users
from src.application.identity_session import (
    AccessTokenIssuer,
    HybridSessionState,
    JavaSessionBridge,
)
from src.application.identity_users import (
    CacheInvalidationError,
    IdentityUsers,
    _bcrypt_input,
)
from src.config import settings


class _Redis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = value
        return True

    async def delete(self, key):
        return self.values.pop(key, None) is not None


class _Java:
    active = True
    fail_logout = False

    async def is_active(self, token, expected_user_id):
        assert expected_user_id == 7
        return self.active

    async def logout(self, token):
        if self.fail_logout:
            raise ConnectionError("remote unavailable")
        self.active = False


@pytest.mark.asyncio
async def test_java_bridge_rejects_wrong_profile_identity(monkeypatch):
    original_client = httpx.AsyncClient
    returned_id = {"value": 8}

    def handler(request):
        assert request.headers["satoken"] == "access-token"
        return httpx.Response(200, json={"code": 200, "data": {"id": returned_id["value"]}})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "src.application.identity_session.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    bridge = JavaSessionBridge("https://java.internal")
    assert not await bridge.is_active("access-token", 7)
    returned_id["value"] = 7
    assert await bridge.is_active("access-token", 7)
    await bridge.close()


@pytest.mark.asyncio
async def test_python_and_legacy_java_sessions_revoke_without_fallthrough():
    redis, java = _Redis(), _Java()
    sessions = HybridSessionState(redis=redis, java=java)
    claims = AccessClaims(7, "python-jti", int(datetime.now(timezone.utc).timestamp()) + 600)
    await sessions.register(claims)
    assert await sessions.is_active("python-token", claims)
    await sessions.revoke("python-token", claims)
    assert not await sessions.is_active("python-token", claims)
    assert java.active  # Python 会话绝不能误调用 Java 登出。

    legacy = AccessClaims(7, "java-jti", claims.expires_at)
    assert await sessions.is_active("java-token", legacy)
    java.fail_logout = True
    with pytest.raises(ConnectionError):
        await sessions.revoke("java-token", legacy)
    assert await sessions.is_active("java-token", legacy)  # 失败后可以重试。
    java.fail_logout = False
    await sessions.revoke("java-token", legacy)
    assert not await sessions.is_active("java-token", legacy)


def test_bcrypt_java_prefix_and_python_jwt_claims():
    password = "password-123"
    spring_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).replace(b"$2b$", b"$2a$", 1)
    assert bcrypt.checkpw(password.encode(), spring_hash)
    assert len(_bcrypt_input("中" * 40)) == 72
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    from cryptography.hazmat.primitives.serialization import NoEncryption, PrivateFormat

    private_pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    public_pem = (
        key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    )
    token, claims = AccessTokenIssuer(private_pem, "tolink-java", ["tolink-java-api"], 7200).sign(
        7, "USER"
    )
    assert AccessTokenVerifier(public_pem, "tolink-java", "tolink-java-api").verify(token) == claims


@pytest.mark.asyncio
async def test_existing_user_login_register_and_admin_writes_on_shared_schema(
    monkeypatch,
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE sys_user (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT, nickname TEXT, email TEXT UNIQUE, phone TEXT, avatar_url TEXT, role TEXT, status INTEGER, bio TEXT, team TEXT, last_login_at DATETIME, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE user_login_event (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, login_source TEXT, created_at DATETIME)"
            )
        )
        old_hash = bcrypt.hashpw(b"old-password", bcrypt.gensalt(prefix=b"2a")).decode()
        await conn.execute(
            text(
                "INSERT INTO sys_user (username,password_hash,email,role,status) VALUES ('old-user',:hash,'old@example.com','USER',1)"
            ),
            {"hash": old_hash},
        )

    @asynccontextmanager
    async def read_context():
        async with session_factory() as session:
            yield session

    @asynccontextmanager
    async def write_context():
        async with session_factory() as session:
            async with session.begin():
                yield session

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    from cryptography.hazmat.primitives.serialization import NoEncryption, PrivateFormat

    private_pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    public_pem = (
        key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    )
    issuer = AccessTokenIssuer(private_pem, "tolink-java", ["tolink-java-api"], 7200)
    verifier = AccessTokenVerifier(public_pem, "tolink-java", "tolink-java-api")
    monkeypatch.setattr("src.application.identity_users.get_db_context", read_context)
    monkeypatch.setattr("src.application.identity_users.write_transaction", write_context)
    monkeypatch.setattr("src.api.management_auth.build_access_token_verifier", lambda: verifier)
    monkeypatch.setattr(AccessTokenIssuer, "from_settings", classmethod(lambda cls: issuer))

    async def no_cache(user_id):
        return None

    monkeypatch.setattr("src.application.identity_users._evict_profile", no_cache)
    users = IdentityUsers(HybridSessionState(redis=_Redis()))
    logged_in = await users.login(" old-user ", "old-password")
    assert logged_in["tokenType"] == "Bearer"
    assert (await users.profile(logged_in["userId"]))["username"] == "old-user"
    await users.update_profile(logged_in["userId"], {"nickname": "新昵称"})
    assert (await users.profile(logged_in["userId"]))["nickname"] == "新昵称"
    registered = await users.register("new-user", "new-password", "new@example.com")
    registered_profile = await users.profile(registered["userId"])
    assert re.fullmatch(r"用户[A-Z0-9]{7}", registered_profile["nickname"])
    assert (await users.list_users(1, 10))["total"] == 2
    await users.update_admin_field(logged_in["userId"], registered["userId"], "role", "ADMIN")
    await users.update_admin_field(logged_in["userId"], registered["userId"], "status", 0)
    await users.update_admin_field(logged_in["userId"], registered["userId"], "status", 0)
    assert (await users.profile(registered["userId"]))["status"] == 0
    with pytest.raises(Exception) as disabled:
        await users.login("new-user", "new-password")
    assert getattr(disabled.value, "code", None) == 20003
    with pytest.raises(Exception) as duplicate:
        await users.register("new-user", "anything", "another@example.com")
    assert getattr(duplicate.value, "code", None) == 20006
    with pytest.raises(Exception) as duplicate_email:
        await users.register("another-user", "anything", "new@example.com")
    assert getattr(duplicate_email.value, "code", None) == 20007
    assert str(duplicate_email.value) == "邮箱已被使用"
    async with session_factory() as session:
        sources = (
            (await session.execute(text("SELECT login_source FROM user_login_event ORDER BY id")))
            .scalars()
            .all()
        )
        new_hash = (
            await session.execute(
                text("SELECT password_hash FROM sys_user WHERE id=:uid"),
                {"uid": registered["userId"]},
            )
        ).scalar_one()
    assert sources == ["LOGIN", "REGISTER"]
    assert new_hash.startswith("$2a$") and bcrypt.checkpw(b"new-password", new_hash.encode())
    await engine.dispose()


def test_blank_credentials_rejected_and_username_trimmed_after_length_check():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        identity_users.LoginRequest(account="   ", password="secret")
    with pytest.raises(ValidationError):
        identity_users.LoginRequest(account="user", password="   ")
    with pytest.raises(ValidationError):
        identity_users.RegisterRequest(username="   ", password="secret", email="valid@example.com")
    assert (
        identity_users.RegisterRequest(
            username=" ab ", password="secret", email="valid@example.com"
        ).username
        == "ab"
    )
    normalized = identity_users.RegisterRequest(
        username=" abc ", password="secret", email="valid@example.com"
    )
    assert normalized.username == "abc"


@pytest.mark.asyncio
async def test_failed_session_registration_rolls_back_new_user(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TABLE sys_user (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT, nickname TEXT, email TEXT UNIQUE, role TEXT, status INTEGER, last_login_at DATETIME)"
            )
        )

    @asynccontextmanager
    async def write_context():
        async with factory() as session:
            async with session.begin():
                yield session

    class FailingSessions:
        async def register(self, claims):
            raise ConnectionError("redis unavailable")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    from cryptography.hazmat.primitives.serialization import NoEncryption, PrivateFormat

    issuer = AccessTokenIssuer(
        key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode(),
        "tolink-java",
        ["tolink-java-api"],
        7200,
    )
    monkeypatch.setattr("src.application.identity_users.write_transaction", write_context)
    monkeypatch.setattr(AccessTokenIssuer, "from_settings", classmethod(lambda cls: issuer))
    monkeypatch.setattr(
        "src.api.management_auth.build_access_token_verifier",
        lambda: AccessTokenVerifier(
            key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode(),
            "tolink-java",
            "tolink-java-api",
        ),
    )
    with pytest.raises(ConnectionError):
        await IdentityUsers(FailingSessions()).register("new-user", "secret", "new@example.com")
    async with factory() as session:
        assert (await session.execute(text("SELECT COUNT(*) FROM sys_user"))).scalar_one() == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_user_routes_require_current_db_role_and_keep_contract(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "iss": "tolink-java",
            "aud": "tolink-java-api",
            "sub": "7",
            "token_use": "access",
            "role": "ADMIN",  # 旧声明不能覆盖 DB 当前角色。
            "iat": now,
            "exp": now + timedelta(hours=1),
            "jti": "java-1",
        },
        key,
        algorithm="RS256",
    )

    class Users:
        role = "USER"

        async def get_user(self, user_id):
            return UserAuthorization(user_id, self.role, 1)

    class UseCases:
        avatar_error = None

        async def profile(self, user_id):
            return {"id": user_id, "username": "old-user", "role": "USER"}

        async def list_users(self, page, size):
            return {
                "items": [],
                "total": 0,
                "page": page,
                "pageSize": size,
                "totalPages": 0,
            }

        async def set_avatar(self, user_id, url):
            if self.avatar_error:
                raise self.avatar_error
            return {"id": user_id, "avatarUrl": url}

    class Storage:
        uploaded = []
        removed = []
        fail_upload = False

        def build_public_url(self, bucket, key):
            return f"https://cdn.example/{bucket}/{key}"

        def upload_bytes(self, bucket, key, content, content_type):
            if self.fail_upload:
                raise OSError("storage unavailable")
            self.uploaded.append(key)

        def remove_object(self, bucket, key):
            self.removed.append(key)

    java = _Java()
    sessions = HybridSessionState(redis=_Redis(), java=java)
    users = Users()
    app = FastAPI()
    app.state.identity_sessions = sessions
    app.state.management_authenticator = ManagementAuthenticator(
        AccessTokenVerifier(pub, "tolink-java", "tolink-java-api"), sessions, users
    )
    use_cases, storage = UseCases(), Storage()
    monkeypatch.setattr(identity_users, "_users", lambda request: use_cases)
    monkeypatch.setattr(identity_users.StorageFactory, "get_storage", lambda: storage)
    app.include_router(identity_users.auth_router)
    app.include_router(identity_users.user_router)
    app.include_router(identity_users.admin_router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (
            await client.post("/api/v1/auth/login", json={"account": "   ", "password": "x"})
        ).json() == {"code": 400, "message": "account: 账号不能为空", "data": None}
        assert (
            await client.post(
                "/api/v1/auth/register",
                json={"username": "ab", "password": "123456", "email": "x@example.com"},
            )
        ).json()["message"] == "username: 用户名长度必须在3-64之间"
        assert (await client.post("/api/v1/auth/logout")).json()["code"] == 200
        assert (
            await client.post("/api/v1/auth/logout", headers={"satoken": "invalid-token"})
        ).json()["code"] == 200
        assert (
            await client.post("/api/v1/auth/login", json={"account": "x", "password": "x"})
        ).status_code == 503
        anonymous_profile = await client.get("/api/v1/user/profile")
        assert anonymous_profile.status_code == 401
        assert anonymous_profile.json()["message"] == "未登录或登录已过期"
        response = await client.get("/api/v1/user/profile", headers={"satoken": token})
        assert response.json()["data"]["id"] == 7
        assert (
            await client.get("/api/v1/admin/users", headers={"satoken": token})
        ).status_code == 403
        users.role = "ADMIN"
        response = await client.get("/api/v1/admin/users", headers={"satoken": token})
        assert response.status_code == 200
        assert response.json()["data"]["pageSize"] == 10
        monkeypatch.setattr(settings, "B1_JAVA_PROTECTED_ROUTES_RETIRED", False)
        assert (
            await client.patch(
                "/api/v1/admin/users/8/status", json={"status": 0}, headers={"satoken": token}
            )
        ).status_code == 503
        for filename, content, message in (
            ("empty.txt", b"", "请选择要上传的文件"),
            ("bad.txt", b"data", "上传文件格式不支持"),
            ("large.png", b"x" * (5 * 1024 * 1024 + 1), "上传大小请限制在 5M 以内"),
        ):
            rejected = await client.post(
                "/api/v1/user/avatar",
                headers={"satoken": token},
                files={"file": (filename, content, "application/octet-stream")},
            )
            assert rejected.status_code == 400
            assert rejected.json() == {"code": 40001, "message": message, "data": None}
        avatar = await client.post(
            "/api/v1/user/avatar",
            headers={"satoken": token},
            files={"file": ("avatar.png", b"image", "application/octet-stream")},
        )
        assert avatar.status_code == 200 and len(storage.uploaded) == 1
        storage.fail_upload = True
        failed_upload = await client.post(
            "/api/v1/user/avatar",
            headers={"satoken": token},
            files={"file": ("avatar.png", b"image", "image/png")},
        )
        assert failed_upload.status_code == 500
        assert failed_upload.json()["code"] == 50002
        storage.fail_upload = False
        use_cases.avatar_error = RuntimeError("database failed")
        assert (
            await client.post(
                "/api/v1/user/avatar",
                headers={"satoken": token},
                files={"file": ("avatar.png", b"image", "image/png")},
            )
        ).status_code == 500
        assert storage.removed == [storage.uploaded[-1]]
        use_cases.avatar_error = CacheInvalidationError("committed")
        assert (
            await client.post(
                "/api/v1/user/avatar",
                headers={"satoken": token},
                files={"file": ("avatar.png", b"image", "image/png")},
            )
        ).status_code == 500
        assert len(storage.removed) == 1  # 已提交的 URL 仍引用此对象。
        await client.post("/api/v1/auth/logout", headers={"satoken": token})
        assert (
            await client.get("/api/v1/user/profile", headers={"satoken": token})
        ).status_code == 401
