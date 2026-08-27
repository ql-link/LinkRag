from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.api import java_access_auth
from src.api.java_access_auth import (
    AuthContext,
    decode_java_access_token,
    require_admin,
    verify_user_token,
)
from src.application.recall_errors import RecallApiError
from src.config import settings


class _Request:
    def __init__(self, token: str | None) -> None:
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


@pytest.fixture
def access_key(tmp_path, monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_path = tmp_path / "java-access-public.pem"
    public_path.write_bytes(public_pem)
    monkeypatch.setattr(settings, "JAVA_ACCESS_JWT_ENABLED", True)
    monkeypatch.setattr(settings, "JAVA_ACCESS_JWT_PUBLIC_KEY_PATH", str(public_path))
    monkeypatch.setattr(settings, "JAVA_ACCESS_JWT_ISSUER", "tolink-java")
    monkeypatch.setattr(settings, "JAVA_ACCESS_JWT_AUDIENCE", "tolink-rag-api")
    monkeypatch.setattr(settings, "JAVA_ACCESS_JWT_TOKEN_USE", "access")
    java_access_auth._load_public_key.cache_clear()
    yield private_key
    java_access_auth._load_public_key.cache_clear()


def _access_token(private_key, **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": "tolink-java",
        "aud": ["tolink-java-api", "tolink-rag-api"],
        "sub": "10000",
        "token_use": "access",
        "role": "ADMIN",
        "iat": now,
        "exp": now + 7200,
        "jti": "token-1",
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


def _db_row(*, status: int = 1, role: str = "USER") -> AsyncMock:
    db = AsyncMock()
    result = SimpleNamespace(first=lambda: SimpleNamespace(id=10000, status=status, role=role))
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_java_access_token_uses_database_current_role(access_key):
    ctx = await verify_user_token(_Request(_access_token(access_key)), _db_row(role="USER"))

    assert ctx.user_id == 10000
    assert ctx.role == "USER"
    assert ctx.token_id == "token-1"


@pytest.mark.asyncio
async def test_disabled_user_rejected_even_when_access_token_is_valid(access_key):
    with pytest.raises(RecallApiError) as exc:
        await verify_user_token(
            _Request(_access_token(access_key)),
            _db_row(status=0),
        )

    assert exc.value.status_code == 401
    assert exc.value.code == "ACCESS_TOKEN_UNAUTHORIZED"


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "other"},
        {"aud": "other"},
        {"token_use": "refresh"},
        {"exp": int(time.time()) - 1},
        {"sub": "0"},
        {"sub": "not-a-number"},
        {"jti": ""},
    ],
)
def test_invalid_access_claims_are_rejected(access_key, overrides):
    with pytest.raises(RecallApiError) as exc:
        decode_java_access_token(_access_token(access_key, **overrides), "req-1")
    assert exc.value.status_code == 401


def test_foreign_rs256_key_is_rejected(access_key):
    foreign_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(RecallApiError):
        decode_java_access_token(_access_token(foreign_key), "req-1")


@pytest.mark.asyncio
async def test_database_role_downgrade_blocks_admin_dependency():
    ctx = AuthContext(
        user_id=10000,
        request_id="req",
        role="USER",
    )
    with pytest.raises(RecallApiError) as exc:
        await require_admin(ctx)
    assert exc.value.status_code == 403


def test_enabled_configuration_requires_valid_public_key(monkeypatch, tmp_path):
    invalid = tmp_path / "invalid.pem"
    invalid.write_text("not a key")
    monkeypatch.setattr(settings, "JAVA_ACCESS_JWT_ENABLED", True)
    monkeypatch.setattr(settings, "JAVA_ACCESS_JWT_PUBLIC_KEY_PATH", str(invalid))
    java_access_auth._load_public_key.cache_clear()
    with pytest.raises(ValueError):
        java_access_auth.validate_java_access_jwt_configuration()
