"""迁移管理 API 的身份边界。真实会话源接入前始终拒绝受保护请求。"""

from dataclasses import dataclass
from typing import Annotated, Protocol

import jwt
from fastapi import Depends, Request
from sqlalchemy import text

from src.api.java_access_auth import _load_public_key, verify_access_claims
from src.api.management_http import BusinessError
from src.application.recall_errors import RecallApiError
from src.config import settings
from src.database import get_db_context


@dataclass(frozen=True)
class AccessClaims:
    user_id: int
    token_id: str
    expires_at: int = 0


@dataclass(frozen=True)
class UserAuthorization:
    user_id: int
    role: str
    status: int


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    role: str


class SessionStateProvider(Protocol):
    async def is_active(self, token: str, claims: AccessClaims) -> bool: ...


class UserAuthorizationRepository(Protocol):
    async def get_user(self, user_id: int) -> UserAuthorization | None: ...


class SqlUserAuthorizationRepository:
    async def get_user(self, user_id: int) -> UserAuthorization | None:
        async with get_db_context() as session:
            row = (
                (
                    await session.execute(
                        text("SELECT id, role, status FROM sys_user WHERE id = :user_id"),
                        {"user_id": user_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return UserAuthorization(
            user_id=int(row["id"]), role=str(row["role"]), status=int(row["status"])
        )


class AccessTokenVerifier:
    """只接受 Java access JWT 的 RS256 签名和固定声明。"""

    def __init__(self, public_key: str, issuer: str, audience: str) -> None:
        if not public_key.strip() or not issuer.strip() or not audience.strip():
            raise ValueError("管理端 JWT 公钥、签发者和受众必须配置")
        self._public_key = public_key
        self._issuer = issuer
        self._audience = audience

    def verify(self, token: str) -> AccessClaims:
        try:
            payload, user_id = verify_access_claims(
                token, self._public_key, self._issuer, self._audience, "access"
            )
            return AccessClaims(
                user_id=user_id, token_id=str(payload["jti"]), expires_at=int(payload["exp"])
            )
        except (jwt.PyJWTError, RecallApiError, ValueError, KeyError, TypeError) as exc:
            raise BusinessError(401, "未登录或登录已过期", 401) from exc


def build_access_token_verifier() -> AccessTokenVerifier:
    """从运行配置加载 Java 公钥；缺少配置时明确失败。"""
    if not settings.JAVA_ACCESS_JWT_ENABLED:
        raise ValueError("JAVA_ACCESS_JWT_ENABLED 未启用")
    return AccessTokenVerifier(
        _load_public_key(settings.JAVA_ACCESS_JWT_PUBLIC_KEY_PATH).decode("utf-8"),
        settings.JAVA_ACCESS_JWT_ISSUER,
        settings.MANAGEMENT_ACCESS_JWT_AUDIENCE,
    )


class ManagementAuthenticator:
    def __init__(
        self,
        verifier: AccessTokenVerifier,
        session_state: SessionStateProvider,
        users: UserAuthorizationRepository,
    ) -> None:
        self._verifier = verifier
        self._session_state = session_state
        self._users = users

    async def authenticate(self, token: str) -> CurrentUser:
        claims = self._verifier.verify(token)
        try:
            active = await self._session_state.is_active(token, claims)
        except Exception as exc:
            raise BusinessError(503, "登录状态暂不可验证", 503) from exc
        if not active:
            raise BusinessError(401, "未登录或登录已过期", 401)
        try:
            user = await self._users.get_user(claims.user_id)
        except Exception as exc:
            raise BusinessError(503, "用户状态暂不可验证", 503) from exc
        if user is None or user.user_id != claims.user_id:
            raise BusinessError(401, "未登录或登录已过期", 401)
        if user.status != 1:
            raise BusinessError(20003, "账号已被禁用", 403)
        if user.role not in {"ADMIN", "USER"}:
            raise BusinessError(403, "权限不足", 403)
        return CurrentUser(user_id=user.user_id, role=user.role)


async def require_login(request: Request) -> CurrentUser:
    token = request.headers.get("satoken")
    if not token:
        raise BusinessError(401, "未登录或登录已过期", 401)
    authenticator: ManagementAuthenticator | None = getattr(
        request.app.state, "management_authenticator", None
    )
    if authenticator is None:
        raise BusinessError(503, "管理端认证尚未配置", 503)
    return await authenticator.authenticate(token)


def require_role(role: str):
    async def dependency(
        user: Annotated[CurrentUser, Depends(require_login)],
    ) -> CurrentUser:
        if user.role != role:
            raise BusinessError(403, "权限不足", 403)
        return user

    return dependency


def require_owner(owner_id: int, user: CurrentUser) -> None:
    """业务层取得可信 owner 后调用；ADMIN 不隐式越权。"""
    if owner_id != user.user_id:
        raise BusinessError(403, "无权访问", 403)
