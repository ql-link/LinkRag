"""B1 user use cases over the existing shared MySQL tables."""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

import bcrypt
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.api.management_http import BusinessError
from src.api.management_auth import AccessClaims
from src.application.identity_session import AccessTokenIssuer, HybridSessionState
from src.cache.fenced_json_cache import FencedJsonCacheStore
from src.database import get_db_context, write_transaction
from src.observability.audit import audit_event


class CacheInvalidationError(RuntimeError):
    """数据库已提交，但跨端用户资料缓存失效失败。"""


def _profile(row: dict) -> dict:
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "nickname": row["nickname"],
        "email": row["email"],
        "phone": row["phone"],
        "avatarUrl": row["avatar_url"],
        "role": row["role"],
        "status": int(row["status"]),
    }


def _shanghai_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)


def _bcrypt_input(password: str) -> bytes:
    # Spring BCrypt 只使用前 72 字节；bcrypt 5.x 对更长输入会抛错。
    return password.encode("utf-8")[:72]


async def _evict_profile(user_id: int) -> None:
    key = f"user:profile:{user_id}"
    try:
        await FencedJsonCacheStore().invalidate(
            data_key=f"cache:{key}",
            fence_key=f"cache:fence:{key}",
            fence_ttl_seconds=2592000,
        )
    except Exception as exc:
        audit_event("USER_PROFILE_CACHE_EVICT", "failed", target_id=user_id)
        raise CacheInvalidationError("用户资料已保存，但缓存失效失败") from exc


async def _record_login(user_id: int, source: str) -> None:
    try:
        async with write_transaction() as session:
            await session.execute(
                text(
                    "INSERT INTO user_login_event (user_id,login_source,created_at) "
                    "VALUES (:uid,:source,:created)"
                ),
                {"uid": user_id, "source": source, "created": _shanghai_now()},
            )
    except Exception:
        audit_event("LOGIN_EVENT_WRITE", "failed", actor_id=user_id)


class IdentityUsers:
    def __init__(self, sessions: HybridSessionState) -> None:
        self._sessions = sessions

    async def _issue(self, user_id: int, role: str) -> tuple[dict, AccessClaims]:
        issuer = AccessTokenIssuer.from_settings()
        token, claims = issuer.sign(user_id, role)
        from src.api.management_auth import build_access_token_verifier

        if build_access_token_verifier().verify(token) != claims:
            raise RuntimeError("签发密钥与验签公钥不匹配")
        await self._sessions.register(claims)
        return {
            "accessToken": token,
            "tokenType": "Bearer",
            "expiresIn": issuer.ttl_seconds,
            "userId": user_id,
        }, claims

    async def login(self, account: str, password: str) -> dict:
        AccessTokenIssuer.from_settings()  # 禁用签发时不触碰账号与密码。
        account = account.strip()
        async with get_db_context() as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT id,password_hash,role,status FROM sys_user "
                            "WHERE username=:account OR email=:account LIMIT 1"
                        ),
                        {"account": account},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise BusinessError(20001, "用户不存在", 404)
        valid = await asyncio.to_thread(
            bcrypt.checkpw,
            _bcrypt_input(password),
            row["password_hash"].encode("utf-8"),
        )
        if not valid:
            raise BusinessError(20002, "密码错误", 401)
        if int(row["status"]) != 1:
            raise BusinessError(20003, "账号已被禁用", 403)
        user_id = int(row["id"])
        async with write_transaction() as session:
            await session.execute(
                text("UPDATE sys_user SET last_login_at=:when WHERE id=:uid"),
                {"when": _shanghai_now(), "uid": user_id},
            )
        result, _ = await self._issue(user_id, str(row["role"]))
        await _record_login(user_id, "LOGIN")
        audit_event("LOGIN_SUCCESS", "success", actor_id=user_id)
        return result

    async def register(self, username: str, password: str, email: str) -> dict:
        AccessTokenIssuer.from_settings()
        username, email = username.strip(), email.strip()
        password_hash = await asyncio.to_thread(
            bcrypt.hashpw, _bcrypt_input(password), bcrypt.gensalt(prefix=b"2a")
        )
        nickname = "用户" + "".join(
            secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(7)
        )
        issued: tuple[dict, AccessClaims] | None = None
        try:
            async with write_transaction() as session:
                result = await session.execute(
                    text(
                        "INSERT INTO sys_user "
                        "(username,password_hash,nickname,email,role,status,last_login_at) "
                        "VALUES (:username,:password_hash,:nickname,:email,'USER',1,:when)"
                    ),
                    {
                        "username": username,
                        "password_hash": password_hash.decode("ascii"),
                        "nickname": nickname,
                        "email": email,
                        "when": _shanghai_now(),
                    },
                )
                user_id = int(result.lastrowid)
                # 会话登记失败时，数据库事务一并回滚，避免客户端收到错误却留下账号。
                issued = await self._issue(user_id, "USER")
        except IntegrityError as exc:
            if issued is not None:
                await self._revoke_failed_registration(issued)
            raise await self._unique_error(username, email) from exc
        except Exception:
            if issued is not None:
                await self._revoke_failed_registration(issued)
            raise
        result, _ = issued
        await _record_login(user_id, "REGISTER")
        audit_event("REGISTER", "success", actor_id=user_id)
        return result

    async def _revoke_failed_registration(
        self, issued: tuple[dict, AccessClaims]
    ) -> None:
        try:
            await self._sessions.revoke(issued[0]["accessToken"], issued[1])
        except Exception:
            # 数据库已回滚；即使 Redis 不可用，鉴权查询也找不到该用户。
            audit_event("REGISTER_SESSION_COMPENSATION", "failed")

    async def _unique_error(self, username: str, email: str) -> BusinessError:
        async with get_db_context() as session:
            username_exists = (
                await session.execute(
                    text("SELECT id FROM sys_user WHERE username=:u LIMIT 1"),
                    {"u": username},
                )
            ).scalar_one_or_none()
        if username_exists is not None:
            return BusinessError(20006, "用户名已存在", 409)
        return BusinessError(20007, "邮箱已被使用", 409)

    async def profile(self, user_id: int) -> dict:
        async with get_db_context() as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT id,username,nickname,email,phone,avatar_url,role,status "
                            "FROM sys_user WHERE id=:uid"
                        ),
                        {"uid": user_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise BusinessError(20001, "用户不存在", 404)
        return _profile(row)

    async def update_profile(self, user_id: int, changes: dict) -> None:
        columns = {
            "nickname": "nickname",
            "email": "email",
            "phone": "phone",
            "avatarUrl": "avatar_url",
        }
        values = {
            columns[k]: v for k, v in changes.items() if k in columns and v is not None
        }
        if "email" in values:
            values["email"] = values["email"].strip() or None
        if not values:
            return
        assignments = ",".join(f"{name}=:{name}" for name in values)
        try:
            async with write_transaction() as session:
                exists = (
                    await session.execute(
                        text("SELECT id FROM sys_user WHERE id=:uid"), {"uid": user_id}
                    )
                ).scalar_one_or_none()
                if exists is None:
                    raise BusinessError(20001, "用户不存在", 404)
                await session.execute(
                    text(f"UPDATE sys_user SET {assignments} WHERE id=:uid"),
                    {**values, "uid": user_id},
                )
        except IntegrityError as exc:
            raise BusinessError(20007, "邮箱已被使用", 409) from exc
        await _evict_profile(user_id)

    async def set_avatar(self, user_id: int, url: str) -> dict:
        await self.update_profile(user_id, {"avatarUrl": url})
        return await self.profile(user_id)

    async def list_users(self, page: int, size: int) -> dict:
        async with get_db_context() as session:
            total = int(
                (
                    await session.execute(text("SELECT COUNT(*) FROM sys_user"))
                ).scalar_one()
            )
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT id,username,nickname,email,phone,avatar_url,role,status "
                            "FROM sys_user ORDER BY created_at DESC,id DESC LIMIT :size OFFSET :offset"
                        ),
                        {"size": size, "offset": (page - 1) * size},
                    )
                )
                .mappings()
                .all()
            )
        return {
            "items": [_profile(row) for row in rows],
            "total": total,
            "page": page,
            "pageSize": size,
            "totalPages": (total + size - 1) // size,
        }

    async def update_admin_field(
        self, actor_id: int, user_id: int, field: str, value: str | int
    ) -> None:
        if field not in {"status", "role"}:
            raise ValueError("unsupported user field")
        async with write_transaction() as session:
            exists = (
                await session.execute(
                    text("SELECT id FROM sys_user WHERE id=:uid"), {"uid": user_id}
                )
            ).scalar_one_or_none()
            if exists is None:
                raise BusinessError(20001, "用户不存在", 404)
            await session.execute(
                text(f"UPDATE sys_user SET {field}=:value WHERE id=:uid"),
                {"value": value, "uid": user_id},
            )
        await _evict_profile(user_id)
        audit_event(
            f"USER_{field.upper()}_CHANGE",
            "success",
            actor_id=actor_id,
            target_id=user_id,
        )
