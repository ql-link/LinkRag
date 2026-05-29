"""``verify_internal_jwt`` 内部凭证校验单测（直接驱动依赖函数）。"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import jwt
import pytest

from src.api.internal_auth import RecallApiError, verify_internal_jwt
from src.config import settings


def _make_token(**overrides) -> str:
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


def _request(headers: dict) -> SimpleNamespace:
    return SimpleNamespace(headers=headers)


def _run(headers: dict):
    return asyncio.run(verify_internal_jwt(_request(headers)))


def test_valid_token_yields_context():
    ctx = _run({"Authorization": f"Bearer {_make_token()}"})
    assert ctx.user_id == 123
    assert ctx.dataset_ids == [1, 2]
    assert ctx.jti == "req-1"
    assert ctx.request_id  # 自动生成


def test_request_id_taken_from_header():
    ctx = _run({"Authorization": f"Bearer {_make_token()}", "X-Request-Id": "req-abc"})
    assert ctx.request_id == "req-abc"


@pytest.mark.parametrize("headers", [
    {},                                   # 无 Authorization
    {"Authorization": "Token xxx"},       # 非 Bearer
    {"Authorization": "Bearer "},         # 空 token
])
def test_missing_or_malformed_header_raises_401(headers):
    with pytest.raises(RecallApiError) as ei:
        _run(headers)
    assert ei.value.status_code == 401
    assert ei.value.code == "RECALL_INTERNAL_UNAUTHORIZED"


@pytest.mark.parametrize("token", [
    _make_token(__secret__="wrong"),
    _make_token(iss="evil"),
    _make_token(aud="other"),
    _make_token(scope="x:y"),
    _make_token(exp=int(time.time()) - 5),
])
def test_invalid_claims_raise_401(token):
    with pytest.raises(RecallApiError) as ei:
        _run({"Authorization": f"Bearer {token}"})
    assert ei.value.status_code == 401


@pytest.mark.parametrize("sub", ["abc", "0", "-1", None])
def test_invalid_subject_raises_401(sub):
    token = _make_token(sub=sub)
    with pytest.raises(RecallApiError) as ei:
        _run({"Authorization": f"Bearer {token}"})
    assert ei.value.status_code == 401


def test_token_without_exp_rejected():
    # require exp：不带 exp 应被拒
    payload = {
        "iss": settings.RECALL_INTERNAL_JWT_ISSUER,
        "aud": settings.RECALL_INTERNAL_JWT_AUDIENCE,
        "scope": settings.RECALL_INTERNAL_JWT_SCOPE,
        "sub": "123",
    }
    token = jwt.encode(payload, settings.RECALL_INTERNAL_JWT_SECRET, algorithm="HS256")
    with pytest.raises(RecallApiError):
        _run({"Authorization": f"Bearer {token}"})


def test_auth_disabled_skips_signature(monkeypatch):
    monkeypatch.setattr(settings, "RECALL_INTERNAL_AUTH_ENABLED", False)
    token = _make_token(__secret__="wrong", exp=int(time.time()) - 100)
    ctx = _run({"Authorization": f"Bearer {token}"})
    assert ctx.user_id == 123
