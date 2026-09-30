"""Java 登录 access JWT 的 Python 独立验证入口。

Java 仍是唯一实际登录与签发方。Python 使用 RS256 公钥验签，再从共享 MySQL 读取
用户当前状态与角色。配置 B1 桥接后，还回调 Java 核验 Sa-Token 会话；不解析其
Redis 内部结构，也不接受旧 recall session token。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import Depends, Request
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.recall_errors import (
    CODE_ACCESS_TOKEN_UNAUTHORIZED,
    CODE_INTERNAL_ERROR,
    RecallApiError,
    _request_id,
)
from src.config import settings
from src.core.storage.auth_identity import load_current_user_identity
from src.database import get_db
from src.observability.logging import truncate_log_value


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Java access JWT 验证后交给业务层的最小可信身份。"""

    user_id: int
    request_id: str
    role: str = "USER"
    token_id: str = ""


def _unauthorized(message: str = "invalid or expired credential") -> RecallApiError:
    return RecallApiError(401, CODE_ACCESS_TOKEN_UNAUTHORIZED, message)


def _extract_bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        raise _unauthorized("missing access token")
    token = header[len("Bearer ") :].strip()
    if not token:
        raise _unauthorized("missing access token")
    return token


@lru_cache(maxsize=4)
def _load_public_key(path_value: str) -> bytes:
    """读取并验证 PEM 公钥；缓存键包含路径，轮换时通过进程重启切换。"""

    if not path_value:
        raise ValueError("JAVA_ACCESS_JWT_PUBLIC_KEY_PATH is required")
    data = Path(path_value).read_bytes()
    load_pem_public_key(data)
    return data


def validate_java_access_jwt_configuration() -> None:
    """启动门禁：启用 access JWT 时公钥缺失或无效必须 fail-fast。"""

    if settings.JAVA_ACCESS_JWT_ENABLED:
        _load_public_key(settings.JAVA_ACCESS_JWT_PUBLIC_KEY_PATH)


def _positive_subject(claims: dict) -> int:
    subject = claims.get("sub")
    if isinstance(subject, bool) or not isinstance(subject, (str, int)):
        raise _unauthorized("invalid subject in credential")
    try:
        user_id = int(subject)
    except (TypeError, ValueError) as exc:
        raise _unauthorized("invalid subject in credential") from exc
    if user_id <= 0:
        raise _unauthorized("invalid subject in credential")
    return user_id


def verify_access_claims(
    token: str, public_key: bytes | str, issuer: str, audience: str, token_use: str
) -> tuple[dict, int]:
    """RAG 与管理 API 共用的 RS256 access JWT 声明校验。"""
    claims = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        audience=audience,
        issuer=issuer,
        options={"require": ["iss", "aud", "exp", "iat", "sub", "jti", "token_use"]},
    )
    if claims.get("token_use") != token_use:
        raise _unauthorized("credential type not permitted")
    if not isinstance(claims.get("jti"), str) or not claims["jti"].strip():
        raise _unauthorized("invalid token id in credential")
    for name in ("iat", "exp"):
        if isinstance(claims.get(name), bool) or not isinstance(claims.get(name), (int, float)):
            raise _unauthorized("invalid time in credential")
    return claims, _positive_subject(claims)


def decode_java_access_token(token: str, request_id: str) -> tuple[dict, int]:
    """严格验证 Java RS256 access JWT，返回可信 claims 与正整数用户 ID。"""

    if not settings.JAVA_ACCESS_JWT_ENABLED:
        raise _unauthorized()
    try:
        return verify_access_claims(
            token,
            _load_public_key(settings.JAVA_ACCESS_JWT_PUBLIC_KEY_PATH),
            settings.JAVA_ACCESS_JWT_ISSUER,
            settings.JAVA_ACCESS_JWT_AUDIENCE,
            settings.JAVA_ACCESS_JWT_TOKEN_USE,
        )
    except (OSError, ValueError, jwt.PyJWTError) as exc:
        logger.bind(
            event="java_access_token_rejected",
            outcome="unauthorized",
            request_id=request_id,
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
        ).info("[java-access-auth] token rejected request_id={}", request_id)
        raise _unauthorized() from exc


async def verify_user_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    """验证 Java 登录 access JWT；配置 B1 桥接时同时核验会话。"""

    token = _extract_bearer_token(request)
    request_id = _request_id(request)
    claims, user_id = decode_java_access_token(token, request_id)
    # Once Python issues sessions, its Redis registration/revocation is the
    # authority for every user-facing API, including RAG and Wiki.  Otherwise
    # a logged-out token remains usable here until its JWT expiry.
    if settings.B1_PYTHON_ISSUER_ENABLED or settings.B1_JAVA_AUTH_BASE_URL:
        from src.api.management_auth import AccessClaims

        sessions = getattr(request.app.state, "identity_sessions", None)
        try:
            active = sessions is not None and await sessions.is_active(
                token,
                AccessClaims(
                    user_id, str(claims["jti"]), int(claims["exp"]), int(claims.get("iat") or 0)
                ),
            )
        except Exception as exc:
            raise RecallApiError(503, CODE_INTERNAL_ERROR, "session lookup failed") from exc
        if not active:
            raise _unauthorized()
    try:
        identity = await load_current_user_identity(db, user_id)
    except Exception as exc:  # noqa: BLE001 - 数据库不可用时鉴权必须 fail-closed
        logger.bind(
            event="java_access_identity_lookup_failed",
            outcome="failed",
            request_id=request_id,
            user_id=user_id,
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
        ).error("[java-access-auth] identity lookup failed request_id={}", request_id)
        raise RecallApiError(500, CODE_INTERNAL_ERROR, "identity lookup failed") from exc
    if identity is None:
        raise _unauthorized()
    return AuthContext(
        user_id=identity.user_id,
        request_id=request_id,
        role=identity.role,
        token_id=str(claims["jti"]),
    )


async def require_admin(
    ctx: AuthContext = Depends(verify_user_token),
) -> AuthContext:
    """管理员依赖只信任数据库当前角色，不信任 JWT 内的角色快照。"""

    if ctx.role != "ADMIN":
        raise RecallApiError(403, CODE_ACCESS_TOKEN_UNAUTHORIZED, "administrator role required")
    return ctx
