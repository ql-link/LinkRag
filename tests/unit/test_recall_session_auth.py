"""``recall_session_auth`` 单测：session token 验签与并发槽。

覆盖验签的成功/失败分支、token 短期可复用语义，以及并发 acquire/release 的
超限拒绝、释放、Redis 故障 fail-open。
"""

from __future__ import annotations

import time

import jwt
import pytest

from src.api import recall_session_auth
from src.application.recall_errors import RecallApiError
from src.api.recall_session_auth import (
    acquire_stream_slot,
    release_stream_slot,
    verify_session_token,
)
from src.config import settings


class _FakeRequest:
    """最小 Request 替身：只需 ``.headers``（dict 支持 .get）。"""

    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


def _token(**overrides) -> str:
    payload = {
        "iss": settings.RECALL_SESSION_JWT_ISSUER,
        "aud": settings.RECALL_SESSION_JWT_AUDIENCE,
        "scope": settings.RECALL_SESSION_JWT_SCOPE,
        "sub": "123",
        "dataset_ids": [1, 2],
        "exp": int(time.time()) + 300,
    }
    payload.update(overrides)
    secret = overrides.pop("_secret", settings.RECALL_SESSION_JWT_SECRET)
    return jwt.encode(payload, secret, algorithm="HS256")


def _req(token: str | None) -> _FakeRequest:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return _FakeRequest(headers)


# ---- 验签 ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_token_yields_context():
    ctx = await verify_session_token(_req(_token()))
    assert ctx.user_id == 123
    assert ctx.dataset_ids == [1, 2]
    assert ctx.request_id  # 自动生成


@pytest.mark.asyncio
async def test_reusable_same_token_twice_both_pass():
    """token 短期可复用：同一 token 连续校验两次都通过（无一次性消费）。"""
    token = _token()
    ctx1 = await verify_session_token(_req(token))
    ctx2 = await verify_session_token(_req(token))
    assert ctx1.user_id == ctx2.user_id == 123


@pytest.mark.asyncio
async def test_missing_header_rejected():
    with pytest.raises(RecallApiError) as exc:
        await verify_session_token(_req(None))
    assert exc.value.status_code == 401
    assert exc.value.code == "RECALL_SESSION_UNAUTHORIZED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"_secret": "wrong-secret"},
        {"iss": "evil"},
        {"aud": "other"},
        {"scope": "x:y"},
        {"exp": int(time.time()) - 10},
    ],
)
async def test_defective_token_rejected(overrides):
    with pytest.raises(RecallApiError) as exc:
        await verify_session_token(_req(_token(**overrides)))
    assert exc.value.status_code == 401
    assert exc.value.code == "RECALL_SESSION_UNAUTHORIZED"


@pytest.mark.asyncio
async def test_foreign_secret_token_rejected():
    """用其它密钥签发、claims 全对的 token 必须被对外端点拒绝（密钥隔离）。"""
    token = jwt.encode(
        {
            "iss": settings.RECALL_SESSION_JWT_ISSUER,
            "aud": settings.RECALL_SESSION_JWT_AUDIENCE,
            "scope": settings.RECALL_SESSION_JWT_SCOPE,
            "sub": "123",
            "dataset_ids": [1],
            "exp": int(time.time()) + 300,
        },
        "some-other-service-secret-not-the-session-key",
        algorithm="HS256",
    )
    with pytest.raises(RecallApiError) as exc:
        await verify_session_token(_req(token))
    assert exc.value.code == "RECALL_SESSION_UNAUTHORIZED"


# ---- 并发槽 --------------------------------------------------------------


class _FakeRedis:
    def __init__(self, start: int = 0) -> None:
        self.store: dict[str, int] = {}
        self._start = start

    async def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, self._start) + 1
        return self.store[key]

    async def decr(self, key: str) -> int:
        self.store[key] = self.store.get(key, self._start) - 1
        return self.store[key]

    async def expire(self, key: str, ttl: int) -> bool:
        return True

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = int(value)


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    for name in ("incr", "decr", "expire", "set"):
        monkeypatch.setattr(recall_session_auth.redis_client, name, getattr(fake, name))
    return fake


@pytest.mark.asyncio
async def test_acquire_under_limit(fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "RECALL_SESSION_MAX_CONCURRENT", 3)
    assert await acquire_stream_slot(123) is True
    assert fake_redis.store["recall:concurrent:123"] == 1


@pytest.mark.asyncio
async def test_acquire_over_limit_rejected_and_rolled_back(fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "RECALL_SESSION_MAX_CONCURRENT", 3)
    fake_redis.store["recall:concurrent:123"] = 3
    assert await acquire_stream_slot(123) is False
    # 超卖被 DECR 回退，计数仍为 3
    assert fake_redis.store["recall:concurrent:123"] == 3


@pytest.mark.asyncio
async def test_release_decrements(fake_redis):
    fake_redis.store["recall:concurrent:123"] = 2
    await release_stream_slot(123)
    assert fake_redis.store["recall:concurrent:123"] == 1


@pytest.mark.asyncio
async def test_release_floor_at_zero(fake_redis):
    fake_redis.store["recall:concurrent:123"] = 0
    await release_stream_slot(123)
    # 负值被重置回 0，避免计数漂移误放行
    assert fake_redis.store["recall:concurrent:123"] == 0


@pytest.mark.asyncio
async def test_acquire_fail_open_on_redis_error(monkeypatch):
    async def _boom(*_a, **_k):
        raise RuntimeError("redis down")

    monkeypatch.setattr(recall_session_auth.redis_client, "incr", _boom)
    # Redis 故障：并发限流是资源保护非鉴权，fail-open 放行。
    assert await acquire_stream_slot(123) is True
