"""B1 user use cases over the existing shared MySQL tables."""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timedelta
from typing import Any, Mapping, cast
from zoneinfo import ZoneInfo

import bcrypt
from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from src.api.management_auth import AccessClaims
from src.api.management_http import BusinessError
from src.application.identity_session import AccessTokenIssuer, HybridSessionState
from src.cache.fenced_json_cache import FencedJsonCacheStore
from src.database import get_db_context, write_transaction
from src.observability.audit import audit_event


class CacheInvalidationError(RuntimeError):
    """数据库已提交，但跨端用户资料缓存失效失败。"""


def _iso(value) -> str | None:
    """DATETIME 列按驱动不同可能返回 datetime 或字符串，统一输出 ISO 文本。"""
    if not value:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _profile(row: Mapping[Any, Any]) -> dict:
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "nickname": row["nickname"],
        "email": row["email"],
        "phone": row["phone"],
        "avatarUrl": row["avatar_url"],
        "role": row["role"],
        "status": int(row["status"]),
        "bio": row.get("bio"),
        "team": row.get("team"),
        "createdAt": _iso(row.get("created_at")),
    }


_PROFILE_COLUMNS = "id,username,nickname,email,phone,avatar_url,role,status,bio,team,created_at"


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


class LoginContext:
    """登录请求来源：IP 与 User-Agent，仅用于管理台登录记录展示。"""

    __slots__ = ("ip", "user_agent")

    def __init__(self, ip: str | None = None, user_agent: str | None = None) -> None:
        self.ip = (ip or "").strip()[:64] or None
        self.user_agent = (user_agent or "").strip()[:255] or None


_NO_CONTEXT = LoginContext()


async def _record_login(user_id: int, source: str, ctx: LoginContext = _NO_CONTEXT) -> None:
    params = {"uid": user_id, "source": source, "created": _shanghai_now(), "ip": ctx.ip, "ua": ctx.user_agent}
    try:
        async with write_transaction() as session:
            await session.execute(
                text(
                    "INSERT INTO user_login_event (user_id,login_source,created_at,ip,user_agent) "
                    "VALUES (:uid,:source,:created,:ip,:ua)"
                ),
                params,
            )
        return
    except Exception:
        pass
    # migration 0043 未执行时退回旧列集合（新事务），成功事件仍要落库：看板活跃统计依赖它。
    try:
        async with write_transaction() as session:
            await session.execute(
                text(
                    "INSERT INTO user_login_event (user_id,login_source,created_at) "
                    "VALUES (:uid,:source,:created)"
                ),
                params,
            )
    except Exception:
        audit_event("LOGIN_EVENT_WRITE", "failed", actor_id=user_id)


async def _record_failure(user_id: int, reason: str, ctx: LoginContext) -> None:
    """登录失败记录（仅账号存在时）；写入失败不影响登录错误的返回。"""
    try:
        async with write_transaction() as session:
            await session.execute(
                text(
                    "INSERT INTO user_login_failure (user_id,reason,ip,user_agent,created_at) "
                    "VALUES (:uid,:reason,:ip,:ua,:created)"
                ),
                {
                    "uid": user_id,
                    "reason": reason,
                    "ip": ctx.ip,
                    "ua": ctx.user_agent,
                    "created": _shanghai_now(),
                },
            )
    except Exception:
        audit_event("LOGIN_FAILURE_WRITE", "failed", target_id=user_id)


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

    async def login(
        self, account: str, password: str, ctx: LoginContext = _NO_CONTEXT
    ) -> dict:
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
        user_id = int(row["id"])
        if not valid:
            await _record_failure(user_id, "BAD_PASSWORD", ctx)
            raise BusinessError(20002, "密码错误", 401)
        if int(row["status"]) != 1:
            await _record_failure(user_id, "DISABLED", ctx)
            raise BusinessError(20003, "账号已被禁用", 403)
        async with write_transaction() as session:
            await session.execute(
                text("UPDATE sys_user SET last_login_at=:when WHERE id=:uid"),
                {"when": _shanghai_now(), "uid": user_id},
            )
        result, _ = await self._issue(user_id, str(row["role"]))
        await _record_login(user_id, "LOGIN", ctx)
        audit_event("LOGIN_SUCCESS", "success", actor_id=user_id)
        return result

    async def register(
        self, username: str, password: str, email: str, ctx: LoginContext = _NO_CONTEXT
    ) -> dict:
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
                user_id = int(cast(CursorResult[Any], result).lastrowid)
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
        login_result, _ = issued
        await _record_login(user_id, "REGISTER", ctx)
        audit_event("REGISTER", "success", actor_id=user_id)
        return login_result

    async def _revoke_failed_registration(self, issued: tuple[dict, AccessClaims]) -> None:
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
                        text(f"SELECT {_PROFILE_COLUMNS} FROM sys_user WHERE id=:uid"),
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
            "bio": "bio",
            "team": "team",
        }
        values = {columns[k]: v for k, v in changes.items() if k in columns and v is not None}
        if "email" in values:
            values["email"] = values["email"].strip() or None
        for optional in ("bio", "team"):
            # 简介 / 团队允许清空：空白字符串存为 NULL。
            if optional in values:
                values[optional] = values[optional].strip() or None
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

    async def refresh(self, token: str, claims: AccessClaims) -> dict:
        """用仍有效的令牌换取新令牌（滑动续期），并撤销旧令牌。"""
        AccessTokenIssuer.from_settings()
        async with get_db_context() as session:
            row = (
                (
                    await session.execute(
                        text("SELECT role,status FROM sys_user WHERE id=:uid"),
                        {"uid": claims.user_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise BusinessError(401, "未登录或登录已过期", 401)
        if int(row["status"]) != 1:
            raise BusinessError(20003, "账号已被禁用", 403)
        result, _ = await self._issue(claims.user_id, str(row["role"]))
        await self._sessions.revoke(token, claims)
        audit_event("TOKEN_REFRESH", "success", actor_id=claims.user_id)
        return result

    async def change_password(
        self, token: str, claims: AccessClaims, current: str, new: str
    ) -> dict:
        """校验当前密码后更新；使该用户此前签发的全部令牌失效，并为当前客户端签发新令牌。"""
        issuer = AccessTokenIssuer.from_settings()
        async with get_db_context() as session:
            row = (
                (
                    await session.execute(
                        text("SELECT password_hash,role FROM sys_user WHERE id=:uid"),
                        {"uid": claims.user_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise BusinessError(20001, "用户不存在", 404)
        valid = await asyncio.to_thread(
            bcrypt.checkpw, _bcrypt_input(current), row["password_hash"].encode("utf-8")
        )
        if not valid:
            raise BusinessError(20008, "当前密码不正确", 400)
        if current == new:
            raise BusinessError(20009, "新密码不能与当前密码相同", 400)
        password_hash = await asyncio.to_thread(
            bcrypt.hashpw, _bcrypt_input(new), bcrypt.gensalt(prefix=b"2a")
        )
        async with write_transaction() as session:
            await session.execute(
                text("UPDATE sys_user SET password_hash=:h WHERE id=:uid"),
                {"h": password_hash.decode("ascii"), "uid": claims.user_id},
            )
        # 先签发新令牌再设置失效时间点：新令牌 iat 取当前秒，失效点取下一秒之前的所有签发。
        result, fresh = await self._issue(claims.user_id, str(row["role"]))
        await self._sessions.revoke_all_before(claims.user_id, fresh.issued_at, issuer.ttl_seconds)
        audit_event("PASSWORD_CHANGE", "success", actor_id=claims.user_id)
        return result

    async def set_avatar(self, user_id: int, url: str) -> dict:
        await self.update_profile(user_id, {"avatarUrl": url})
        return await self.profile(user_id)

    async def list_users(self, page: int, size: int) -> dict:
        async with get_db_context() as session:
            total = int((await session.execute(text("SELECT COUNT(*) FROM sys_user"))).scalar_one())
            rows = (
                (
                    await session.execute(
                        text(
                            f"SELECT {_PROFILE_COLUMNS} FROM sys_user "
                            "ORDER BY created_at DESC,id DESC LIMIT :size OFFSET :offset"
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

    async def admin_reset_password(
        self, actor_id: int, user_id: int, new_password: str | None = None
    ) -> dict:
        """管理员重置用户密码：未指定时生成 12 位临时密码；使该用户已签发的全部令牌失效。

        临时密码只在本次响应中返回一次，不落日志、不入审计明文。
        """
        issuer = AccessTokenIssuer.from_settings()
        password = new_password or "".join(
            secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789") for _ in range(12)
        )
        password_hash = await asyncio.to_thread(
            bcrypt.hashpw, _bcrypt_input(password), bcrypt.gensalt(prefix=b"2a")
        )
        async with write_transaction() as session:
            exists = (
                await session.execute(text("SELECT id FROM sys_user WHERE id=:uid"), {"uid": user_id})
            ).scalar_one_or_none()
            if exists is None:
                raise BusinessError(20001, "用户不存在", 404)
            await session.execute(
                text("UPDATE sys_user SET password_hash=:h WHERE id=:uid"),
                {"h": password_hash.decode("ascii"), "uid": user_id},
            )
        # 失效点取当前秒之后：此刻之前签发的令牌全部作废，用户需用新密码重新登录。
        await self._sessions.revoke_all_before(
            user_id, int(datetime.now().timestamp()) + 1, issuer.ttl_seconds
        )
        audit_event("USER_PASSWORD_RESET", "success", actor_id=actor_id, target_id=user_id)
        return {"temporaryPassword": None if new_password else password}

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


_ADMIN_SORTS = {
    "created": "u.created_at DESC,u.id DESC",
    "lastLogin": "u.last_login_at IS NULL,u.last_login_at DESC,u.id DESC",
}


async def search_users(
    page: int,
    size: int,
    keyword: str | None = None,
    role: str | None = None,
    status: int | None = None,
    sort: str = "created",
) -> dict:
    """管理台用户列表：关键字（用户名 / 昵称 / 邮箱 / ID）+ 角色 / 状态筛选，附带知识库数、近 30 天 Token 与最近登录。"""
    where, params = ["1=1"], {}
    if keyword and keyword.strip():
        kw = keyword.strip()
        params["kw"] = f"%{kw}%"
        clause = "(u.username LIKE :kw OR u.nickname LIKE :kw OR u.email LIKE :kw"
        if kw.lstrip("#").isdigit():
            params["uid"] = int(kw.lstrip("#"))
            clause += " OR u.id=:uid"
        where.append(clause + ")")
    if role:
        where.append("u.role=:role")
        params["role"] = role
    if status is not None:
        where.append("u.status=:status")
        params["status"] = status
    cond = " AND ".join(where)
    since = _shanghai_now() - timedelta(days=30)
    async with get_db_context() as session:
        total = int(
            (
                await session.execute(text(f"SELECT COUNT(*) FROM sys_user u WHERE {cond}"), params)
            ).scalar_one()
        )
        rows = (
            (
                await session.execute(
                    text(
                        f"SELECT u.id,u.username,u.nickname,u.email,u.phone,u.avatar_url,u.role,u.status,"
                        f"u.bio,u.team,u.created_at,u.last_login_at FROM sys_user u WHERE {cond} "
                        f"ORDER BY {_ADMIN_SORTS.get(sort, _ADMIN_SORTS['created'])} "
                        "LIMIT :size OFFSET :offset"
                    ),
                    {**params, "size": size, "offset": (page - 1) * size},
                )
            )
            .mappings()
            .all()
        )
        ids = [int(r["id"]) for r in rows]
        datasets: dict[int, int] = {}
        tokens: dict[int, int] = {}
        if ids:
            marks = ",".join(f":i{n}" for n in range(len(ids)))
            idp = {f"i{n}": v for n, v in enumerate(ids)}
            for r in (
                await session.execute(
                    text(
                        f"SELECT user_id,COUNT(*) AS n FROM dataset WHERE is_deleted=0 "
                        f"AND user_id IN ({marks}) GROUP BY user_id"
                    ),
                    idp,
                )
            ).mappings():
                datasets[int(r["user_id"])] = int(r["n"])
            for r in (
                await session.execute(
                    text(
                        f"SELECT user_id,SUM(total_tokens) AS n FROM llm_usage_log WHERE created_at>=:since "
                        f"AND user_id IN ({marks}) GROUP BY user_id"
                    ),
                    {**idp, "since": since},
                )
            ).mappings():
                tokens[int(r["user_id"])] = int(r["n"] or 0)
    items = []
    for r in rows:
        uid = int(r["id"])
        items.append(
            {
                **_profile(r),
                "lastLoginAt": _iso(r.get("last_login_at")),
                "datasetCount": datasets.get(uid, 0),
                "tokens30d": tokens.get(uid, 0),
            }
        )
    return {
        "items": items,
        "total": total,
        "page": page,
        "pageSize": size,
        "totalPages": (total + size - 1) // size,
    }


async def user_detail(user_id: int) -> dict:
    """管理台用户详情：资料 + 知识库 / 对话 / Token / 自带模型配置统计 + 最近知识库 + 最近登录记录。"""
    since = _shanghai_now() - timedelta(days=30)
    async with get_db_context() as session:
        row = (
            (
                await session.execute(
                    text(f"SELECT {_PROFILE_COLUMNS},last_login_at FROM sys_user WHERE id=:uid"),
                    {"uid": user_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise BusinessError(20001, "用户不存在", 404)
        p = {"uid": user_id, "since": since}
        files = (
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS n,COALESCE(SUM(file_size),0) AS bytes FROM document_original_file "
                        "WHERE user_id=:uid AND is_deleted=0"
                    ),
                    p,
                )
            )
            .mappings()
            .one()
        )
        dataset_rows = (
            (
                await session.execute(
                    text(
                        "SELECT d.id,d.name,d.status,d.updated_at,COUNT(f.id) AS file_count,"
                        "COALESCE(SUM(f.file_size),0) AS bytes FROM dataset d "
                        "LEFT JOIN document_original_file f ON f.dataset_id=d.id AND f.is_deleted=0 "
                        "WHERE d.user_id=:uid AND d.is_deleted=0 GROUP BY d.id,d.name,d.status,d.updated_at "
                        "ORDER BY d.updated_at DESC"
                    ),
                    p,
                )
            )
            .mappings()
            .all()
        )
        conversations = (
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS total,COALESCE(SUM(created_at>=:since),0) AS recent "
                        "FROM chat_conversation WHERE user_id=:uid"
                    ),
                    p,
                )
            )
            .mappings()
            .one()
        )
        usage = (
            (
                await session.execute(
                    text(
                        "SELECT COALESCE(SUM(prompt_tokens),0) AS prompt,COALESCE(SUM(completion_tokens),0) AS completion,"
                        "COALESCE(SUM(total_tokens),0) AS total FROM llm_usage_log WHERE user_id=:uid AND created_at>=:since"
                    ),
                    p,
                )
            )
            .mappings()
            .one()
        )
        configs = (
            (
                await session.execute(
                    text(
                        "SELECT DISTINCT c.provider_type,s.provider_name FROM llm_model_config c "
                        "LEFT JOIN llm_system_provider s ON s.id=c.provider_id "
                        "WHERE c.scope='USER' AND c.owner_user_id=:uid"
                    ),
                    p,
                )
            )
            .mappings()
            .all()
        )
        config_count = int(
            (
                await session.execute(
                    text("SELECT COUNT(*) FROM llm_model_config WHERE scope='USER' AND owner_user_id=:uid"), p
                )
            ).scalar_one()
        )
        logins = await _recent_logins(session, user_id)
    return {
        **_profile(row),
        "lastLoginAt": _iso(row.get("last_login_at")),
        "stats": {
            "datasetCount": len(dataset_rows),
            "fileCount": int(files["n"] or 0),
            "fileBytes": int(files["bytes"] or 0),
            "conversationCount": int(conversations["total"] or 0),
            "conversations30d": int(conversations["recent"] or 0),
            "promptTokens30d": int(usage["prompt"] or 0),
            "completionTokens30d": int(usage["completion"] or 0),
            "tokens30d": int(usage["total"] or 0),
            "modelConfigCount": config_count,
            "modelProviders": [c["provider_name"] or c["provider_type"] for c in configs],
        },
        "datasets": [
            {
                "id": int(d["id"]),
                "name": d["name"],
                "status": d["status"],
                "fileCount": int(d["file_count"] or 0),
                "fileBytes": int(d["bytes"] or 0),
                "updatedAt": _iso(d["updated_at"]),
            }
            for d in dataset_rows
        ],
        "recentLogins": logins,
    }


async def _recent_logins(session, user_id: int, limit: int = 10) -> list[dict]:
    """最近登录记录：成功事件 + 失败记录按时间合并；migration 0043 未执行时只返回成功事件（无 IP / UA）。"""
    p = {"uid": user_id, "limit": limit}

    async def rows(sql: str) -> list | None:
        try:
            return list((await session.execute(text(sql), p)).mappings().all())
        except Exception:
            await session.rollback()  # 只读会话，回滚后可继续查询
            return None

    ok = await rows(
        "SELECT created_at,login_source,ip,user_agent FROM user_login_event "
        "WHERE user_id=:uid ORDER BY created_at DESC LIMIT :limit"
    )
    if ok is None:
        ok = await rows(
            "SELECT created_at,login_source FROM user_login_event "
            "WHERE user_id=:uid ORDER BY created_at DESC LIMIT :limit"
        ) or []
    failed = await rows(
        "SELECT created_at,reason,ip,user_agent FROM user_login_failure "
        "WHERE user_id=:uid ORDER BY created_at DESC LIMIT :limit"
    ) or []
    items = [
        {
            "time": _iso(r["created_at"]),
            "success": True,
            "source": r["login_source"],
            "reason": None,
            "ip": r.get("ip"),
            "userAgent": r.get("user_agent"),
        }
        for r in ok
    ] + [
        {
            "time": _iso(r["created_at"]),
            "success": False,
            "source": None,
            "reason": r["reason"],
            "ip": r["ip"],
            "userAgent": r["user_agent"],
        }
        for r in failed
    ]
    items.sort(key=lambda r: r["time"] or "", reverse=True)
    return items[:limit]
