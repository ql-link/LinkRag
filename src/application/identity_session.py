"""B1 access-token session state. The Java bridge uses its existing protected API."""

from __future__ import annotations

import math
import time
from pathlib import Path
from uuid import uuid4

import httpx
import jwt

from src.api.management_auth import AccessClaims
from src.cache.redis_client import RedisClient, redis_client
from src.config import settings


class JavaSessionBridge:
    def __init__(self, base_url: str, timeout_seconds: float = 2.0) -> None:
        if not base_url.startswith(("https://", "http://")):
            raise ValueError("Java auth URL 必须是 HTTP(S) 地址")
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_seconds, base_url=self._base_url)

    async def is_active(self, token: str, expected_user_id: int) -> bool:
        response = await self._client.get("/api/v1/user/profile", headers={"satoken": token})
        if response.status_code in {401, 403}:
            return False
        response.raise_for_status()
        body = response.json()
        data = body.get("data")
        return (
            body.get("code") == 200
            and isinstance(data, dict)
            and str(data.get("id")) == str(expected_user_id)
        )

    async def logout(self, token: str) -> None:
        response = await self._client.post("/api/v1/auth/logout", headers={"satoken": token})
        response.raise_for_status()
        if response.json().get("code") != 200:
            raise RuntimeError("Java 会话注销未成功")

    async def close(self) -> None:
        await self._client.aclose()


class HybridSessionState:
    """Python-issued sessions live in Redis; Java-issued sessions are checked by Java."""

    def __init__(
        self, redis: RedisClient | None = None, java: JavaSessionBridge | None = None
    ) -> None:
        self._redis = redis or redis_client
        self._java = java

    async def close(self) -> None:
        if self._java is not None:
            await self._java.close()

    @staticmethod
    def _active_key(jti: str) -> str:
        return f"auth:access:active:{jti}"

    @staticmethod
    def _revoked_key(jti: str) -> str:
        return f"auth:access:revoked:{jti}"

    @staticmethod
    def _not_before_key(user_id: int) -> str:
        return f"auth:access:not-before:{user_id}"

    async def is_active(self, token: str, claims: AccessClaims) -> bool:
        if await self._redis.get(self._revoked_key(claims.token_id)):
            return False
        # 修改密码等操作会使该用户此前签发的全部令牌失效（按签发时间判断）。
        not_before = await self._redis.get(self._not_before_key(claims.user_id))
        if not_before is not None and claims.issued_at and claims.issued_at < int(not_before):
            return False
        owner = await self._redis.get(self._active_key(claims.token_id))
        if owner is not None:
            return owner == str(claims.user_id)
        if self._java is None:
            return False
        return await self._java.is_active(token, claims.user_id)

    async def register(self, claims: AccessClaims) -> None:
        ttl = math.ceil(claims.expires_at - time.time())
        if ttl <= 0:
            raise ValueError("不能登记过期令牌")
        if not await self._redis.set(
            self._active_key(claims.token_id), str(claims.user_id), ex=ttl
        ):
            raise RuntimeError("登录态登记失败")

    async def revoke(self, token: str, claims: AccessClaims) -> None:
        ttl = max(1, math.ceil(claims.expires_at - time.time()))
        local_owner = await self._redis.get(self._active_key(claims.token_id))
        if local_owner is not None:
            if local_owner != str(claims.user_id):
                raise RuntimeError("登录态归属不一致")
        elif self._java is not None:
            # Java 先注销。若远端失败，调用方仍可持原令牌重试。
            await self._java.logout(token)
        else:
            raise RuntimeError("Java 会话注销接口未配置")
        if not await self._redis.set(self._revoked_key(claims.token_id), "1", ex=ttl):
            raise RuntimeError("登录态撤销失败")
        if local_owner is not None:
            await self._redis.delete(self._active_key(claims.token_id))

    async def revoke_all_before(self, user_id: int, issued_before: int, ttl_seconds: int) -> None:
        """使 ``issued_before`` 之前签发给该用户的令牌全部失效；TTL 取令牌最长有效期即可。"""
        if not await self._redis.set(
            self._not_before_key(user_id), str(issued_before), ex=max(1, ttl_seconds)
        ):
            raise RuntimeError("登录态撤销失败")


class AccessTokenIssuer:
    def __init__(
        self, private_key: str, issuer: str, audiences: list[str], ttl_seconds: int
    ) -> None:
        if not private_key.strip() or not audiences or ttl_seconds <= 0:
            raise ValueError("access token 签发配置不完整")
        self._private_key = private_key
        self._issuer = issuer
        self._audiences = audiences
        self._ttl = ttl_seconds

    @classmethod
    def from_settings(cls) -> AccessTokenIssuer:
        if not (
            settings.B1_PYTHON_ISSUER_ENABLED
            and settings.B1_JAVA_PROTECTED_ROUTES_RETIRED
            and settings.B1_ACCESS_JWT_PRIVATE_KEY_PATH
        ):
            raise RuntimeError("Python 登录签发尚未启用")
        return cls(
            Path(settings.B1_ACCESS_JWT_PRIVATE_KEY_PATH).read_text(encoding="utf-8"),
            settings.JAVA_ACCESS_JWT_ISSUER,
            [x.strip() for x in settings.B1_ACCESS_JWT_AUDIENCES.split(",") if x.strip()],
            settings.B1_ACCESS_TOKEN_TTL_SECONDS,
        )

    def sign(self, user_id: int, role: str) -> tuple[str, AccessClaims]:
        issued_at = int(time.time())
        expires_at = issued_at + self._ttl
        token_id = str(uuid4())
        token = jwt.encode(
            {
                "iss": self._issuer,
                "aud": self._audiences,
                "sub": str(user_id),
                "token_use": "access",
                "role": role,
                "iat": issued_at,
                "exp": expires_at,
                "jti": token_id,
            },
            self._private_key,
            algorithm="RS256",
        )
        return token, AccessClaims(user_id, token_id, expires_at, issued_at)

    @property
    def ttl_seconds(self) -> int:
        return self._ttl


def build_session_state() -> HybridSessionState:
    java = (
        JavaSessionBridge(settings.B1_JAVA_AUTH_BASE_URL, settings.B1_JAVA_AUTH_TIMEOUT_SECONDS)
        if settings.B1_JAVA_AUTH_BASE_URL
        else None
    )
    return HybridSessionState(java=java)
