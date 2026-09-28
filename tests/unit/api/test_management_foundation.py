from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import Depends, FastAPI
from pydantic import BaseModel

from src.api.management_auth import (
    AccessTokenVerifier,
    CurrentUser,
    ManagementAuthenticator,
    UserAuthorization,
    require_login,
    require_owner,
    require_role,
)
from src.api.management_http import BusinessError, ManagementRouter, success


class _Body(BaseModel):
    count: int


class _Sessions:
    active = True
    fail = False

    async def is_active(self, token, claims):
        if self.fail:
            raise ConnectionError("session store offline")
        return self.active


class _Users:
    user = UserAuthorization(7, "USER", 1)

    async def get_user(self, user_id):
        return self.user


@pytest.fixture
def auth_fixture():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = (
        key.public_key()
        .public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    sessions, users = _Sessions(), _Users()
    auth = ManagementAuthenticator(
        AccessTokenVerifier(pub, "tolink-java", "tolink-java-api"), sessions, users
    )

    def make_token(**changes):
        now = datetime.now(timezone.utc)
        payload = {
            "iss": "tolink-java",
            "aud": "tolink-java-api",
            "sub": "7",
            "token_use": "access",
            "iat": now,
            "exp": now + timedelta(hours=1),
            "jti": "jwt-1",
            "role": "ADMIN",  # 令牌中的旧角色必须被 DB 当前角色覆盖。
        }
        payload.update(changes)
        return jwt.encode(payload, key, algorithm="RS256")

    return auth, sessions, users, make_token


@pytest.mark.asyncio
async def test_management_http_and_auth_isolation(auth_fixture):
    auth, sessions, users, make_token = auth_fixture
    app = FastAPI()
    app.state.management_authenticator = auth
    router = ManagementRouter(prefix="/management")

    @router.post("/value")
    async def value(body: _Body, user: CurrentUser = Depends(require_login)):
        return success({"user_id": user.user_id, "count": body.count})

    @router.get("/admin")
    async def admin(user: CurrentUser = Depends(require_role("ADMIN"))):
        return success(user.user_id)

    @router.get("/owned")
    async def owned(user: CurrentUser = Depends(require_login)):
        require_owner(8, user)
        return success()

    @router.get("/missing")
    async def missing():
        raise BusinessError(20001, "用户不存在", 404)

    @router.get("/conflict")
    async def conflict():
        raise BusinessError(20006, "用户名已存在", 409)

    @router.get("/binding")
    async def binding():
        raise BusinessError(10028, "数据集模型绑定不合法", 400,
                            data={"field": "dense_embedding_config_id"})

    @router.get("/broken")
    async def broken():
        raise RuntimeError("sensitive internal detail")

    @app.post("/existing")
    async def existing(body: _Body):
        return body

    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post("/existing", json={})).status_code == 422
        token = make_token()
        headers = {"satoken": token}
        assert (
            await client.post("/management/value", json={}, headers=headers)
        ).json() == {"code": 400, "message": "请求参数不合法", "data": None}
        assert (
            await client.post("/management/value", json={}, headers=headers)
        ).status_code == 400
        assert (
            await client.post("/management/value", json={"count": 1})
        ).status_code == 401
        ok = await client.post("/management/value", json={"count": 1}, headers=headers)
        assert ok.json() == {
            "code": 200,
            "message": "success",
            "data": {"user_id": 7, "count": 1},
        }
        spoofed = await client.post(
            "/management/value", json={"count": 2, "user_id": 8}, headers=headers
        )
        assert spoofed.json()["data"]["user_id"] == 7
        assert (
            await client.get("/management/admin", headers=headers)
        ).status_code == 403
        assert (
            await client.get("/management/owned", headers=headers)
        ).status_code == 403
        assert (await client.get("/management/missing")).json()["code"] == 20001
        assert (await client.get("/management/conflict")).status_code == 409
        assert (await client.get("/management/binding")).json()["data"] == {
            "field": "dense_embedding_config_id"
        }
        broken = await client.get("/management/broken")
        assert broken.status_code == 500
        assert broken.json() == {"code": 50001, "message": "系统内部错误", "data": None}
        users.user = UserAuthorization(7, "ADMIN", 1)
        assert (
            await client.get("/management/admin", headers=headers)
        ).status_code == 200
        users.user = UserAuthorization(7, "USER", 0)
        assert (
            await client.post("/management/value", json={"count": 1}, headers=headers)
        ).json()["code"] == 20003
        users.user = UserAuthorization(7, "USER", 1)
        sessions.active = False
        assert (
            await client.get("/management/admin", headers=headers)
        ).status_code == 401
        sessions.active = True
        users.user = None
        assert (
            await client.get("/management/admin", headers=headers)
        ).status_code == 401
        users.user = UserAuthorization(7, "USER", 1)
        sessions.fail = True
        assert (
            await client.get("/management/admin", headers=headers)
        ).status_code == 503


@pytest.mark.parametrize(
    "changes",
    [
        {"aud": "tolink-rag-frontend"},
        {"iss": "other"},
        {"token_use": "session"},
        {"sub": "0"},
        {"jti": ""},
        {"exp": datetime(2000, 1, 1, tzinfo=timezone.utc)},
    ],
)
def test_invalid_access_claims_rejected(auth_fixture, changes):
    verifier = auth_fixture[0]._verifier
    with pytest.raises(BusinessError) as error:
        verifier.verify(auth_fixture[3](**changes))
    assert error.value.http_status == 401


def test_hs256_cannot_be_used_as_management_token(auth_fixture):
    with pytest.raises(BusinessError):
        auth_fixture[0]._verifier.verify(
            jwt.encode({"sub": "7"}, "session-secret" * 3, algorithm="HS256")
        )
