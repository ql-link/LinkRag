"""接入应用身份：应用凭证校验与影子用户映射。

接入应用（如 Link Resume）以 ``Authorization: Bearer <client_id>.<secret>`` 调用
``/api/v1/apps/*``，并通过 ``X-App-User-Id`` 声明其用户。凭证校验通过后，外部用户
在本应用命名空间内映射为唯一的影子 ``sys_user``；此后所有数据隔离沿用 ``user_id``。

影子用户约定：``app_code`` 为应用编码、``password_hash`` 为不可校验的哨兵值、
``email`` 为空。密码登录与 Web token 鉴权均拒绝 ``app_code <> 'tolink'`` 的用户。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, cast

import bcrypt
from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from src.database import get_db_context, write_transaction
from src.observability.audit import audit_event

TOLINK_APP_CODE = "tolink"
# 非 bcrypt 格式：bcrypt.checkpw 对其恒失败，登录路径另有显式 app_code 拦截。
SHADOW_PASSWORD_SENTINEL = "!app-shadow"

_EXTERNAL_USER_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_APP_CODE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_CREDENTIAL_CACHE_TTL_SECONDS = 60.0
_CREDENTIAL_CACHE_SIZE = 64
_BINDING_REREAD_DELAYS = (0.0, 0.05, 0.2)


class AppIdentityError(Exception):
    """应用鉴权失败；由 API 层映射为 HTTP 错误。"""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class AppClient:
    id: int
    app_code: str
    client_id: str
    default_dense_config_id: int | None
    default_sparse_config_id: int | None


@dataclass(frozen=True, slots=True)
class ShadowUser:
    user_id: int
    default_dataset_id: int | None


def is_valid_app_code(value: str) -> bool:
    return bool(_APP_CODE.fullmatch(value)) and value != TOLINK_APP_CODE


def validate_external_user_id(value: str | None) -> str:
    if value is None or not _EXTERNAL_USER_ID.fullmatch(value):
        raise AppIdentityError(400, "APP_USER_ID_INVALID", "invalid X-App-User-Id")
    return value


def shadow_username(app_code: str) -> str:
    """``{app_code}_{20 位随机 hex}``：不超过 64 字符，不含外部 ID。

    必须不可预测：若由外部 ID 推导，Web 注册可抢先占用该用户名，使对应外部用户
    首次访问永远撞 ``uk_username``。用户名不参与鉴权，映射只以 ``app_user_binding`` 为准。
    """

    return f"{app_code}_{secrets.token_hex(10)}"


def hash_secret(secret: str) -> str:
    return bcrypt.hashpw(secret.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def _parse_credential(token: str) -> tuple[str, str]:
    client_id, sep, secret = token.partition(".")
    if not sep or not client_id or not secret:
        raise AppIdentityError(401, "APP_CREDENTIAL_INVALID", "invalid app credential")
    return client_id, secret


class _CredentialCache:
    """进程内 LRU：key 为凭证 sha256，避免每个请求都做 bcrypt。

    轮换或停用后旧凭证最长仍可用 ``_CREDENTIAL_CACHE_TTL_SECONDS``。
    """

    def __init__(self) -> None:
        self._entries: OrderedDict[str, tuple[float, AppClient]] = OrderedDict()

    def get(self, key: str) -> AppClient | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, client = entry
        if expires_at < time.monotonic():
            self._entries.pop(key, None)
            return None
        self._entries.move_to_end(key)
        return client

    def put(self, key: str, client: AppClient) -> None:
        self._entries[key] = (time.monotonic() + _CREDENTIAL_CACHE_TTL_SECONDS, client)
        self._entries.move_to_end(key)
        while len(self._entries) > _CREDENTIAL_CACHE_SIZE:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()


credential_cache = _CredentialCache()


def _client_from_row(row: Any) -> AppClient:
    return AppClient(
        id=int(row["id"]),
        app_code=str(row["app_code"]),
        client_id=str(row["client_id"]),
        default_dense_config_id=(
            int(row["default_dense_config_id"])
            if row["default_dense_config_id"] is not None
            else None
        ),
        default_sparse_config_id=(
            int(row["default_sparse_config_id"])
            if row["default_sparse_config_id"] is not None
            else None
        ),
    )


async def verify_app_credential(token: str) -> AppClient:
    """校验 ``<client_id>.<secret>``；未知、错误或停用的凭证统一拒绝。"""

    client_id, secret = _parse_credential(token)
    cache_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    cached = credential_cache.get(cache_key)
    if cached is not None:
        return cached
    async with get_db_context() as db:
        row = (
            (
                await db.execute(
                    text(
                        "SELECT id,app_code,client_id,secret_hash,status,"
                        "default_dense_config_id,default_sparse_config_id "
                        "FROM app_client WHERE client_id=:cid"
                    ),
                    {"cid": client_id},
                )
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        raise AppIdentityError(401, "APP_CREDENTIAL_INVALID", "invalid app credential")
    try:
        valid = await asyncio.to_thread(
            bcrypt.checkpw,
            secret.encode("utf-8"),
            str(row["secret_hash"]).encode("utf-8"),
        )
    except ValueError:
        valid = False
    if not valid:
        raise AppIdentityError(401, "APP_CREDENTIAL_INVALID", "invalid app credential")
    if row["status"] != "ACTIVE":
        raise AppIdentityError(403, "APP_DISABLED", "app client disabled")
    client = _client_from_row(row)
    credential_cache.put(cache_key, client)
    return client


async def _find_binding(app_code: str, external_user_id: str) -> dict | None:
    async with get_db_context() as db:
        row = (
            (
                await db.execute(
                    text(
                        "SELECT b.user_id,b.default_dataset_id,u.status,u.app_code "
                        "FROM app_user_binding b JOIN sys_user u ON u.id=b.user_id "
                        "WHERE b.app_code=:app AND b.external_user_id=:ext"
                    ),
                    {"app": app_code, "ext": external_user_id},
                )
            )
            .mappings()
            .one_or_none()
        )
    return dict(row) if row is not None else None


async def _create_shadow_user(app_code: str, external_user_id: str) -> None:
    async with write_transaction() as db:
        result = await db.execute(
            text(
                "INSERT INTO sys_user "
                "(username,password_hash,nickname,email,role,status,app_code) "
                "VALUES (:username,:password,:nickname,NULL,'USER',1,:app)"
            ),
            {
                "username": shadow_username(app_code),
                "password": SHADOW_PASSWORD_SENTINEL,
                "nickname": f"{app_code} 用户",
                "app": app_code,
            },
        )
        user_id = int(cast(CursorResult[Any], result).lastrowid)
        await db.execute(
            text(
                "INSERT INTO app_user_binding (app_code,external_user_id,user_id) "
                "VALUES (:app,:ext,:uid)"
            ),
            {"app": app_code, "ext": external_user_id, "uid": user_id},
        )
    audit_event("APP_SHADOW_USER_CREATE", "success", actor_id=user_id)


async def resolve_shadow_user(app: AppClient, external_user_id: str) -> ShadowUser:
    """幂等解析影子用户；首次访问时在单事务内创建 ``sys_user`` 与绑定。

    并发首次请求由 ``uk_app_user_binding_external`` 兜底：失败方整事务回滚（不留孤儿
    ``sys_user``）并重读赢家写入的绑定。
    """

    external_user_id = validate_external_user_id(external_user_id)
    row = await _find_binding(app.app_code, external_user_id)
    if row is None:
        try:
            await _create_shadow_user(app.app_code, external_user_id)
        except IntegrityError:
            pass
        # 竞态失败方：赢家事务提交可能略晚于本方唯一键冲突，短暂重读直到可见。
        for delay in _BINDING_REREAD_DELAYS:
            await asyncio.sleep(delay)
            row = await _find_binding(app.app_code, external_user_id)
            if row is not None:
                break
        if row is None:
            raise AppIdentityError(
                503, "APP_USER_UNAVAILABLE", "shadow user unavailable"
            )
    if row["app_code"] != app.app_code:
        # 绑定只应指向本应用影子用户；不一致说明数据被人工篡改，fail-closed。
        raise AppIdentityError(403, "APP_USER_DISABLED", "app user disabled")
    if int(row["status"]) != 1:
        raise AppIdentityError(403, "APP_USER_DISABLED", "app user disabled")
    return ShadowUser(
        user_id=int(row["user_id"]),
        default_dataset_id=(
            int(row["default_dataset_id"])
            if row["default_dataset_id"] is not None
            else None
        ),
    )


async def set_default_dataset(app_code: str, user_id: int, dataset_id: int) -> None:
    async with write_transaction() as db:
        await db.execute(
            text(
                "UPDATE app_user_binding SET default_dataset_id=:did "
                "WHERE app_code=:app AND user_id=:uid"
            ),
            {"did": dataset_id, "app": app_code, "uid": user_id},
        )


# ---------------------------------------------------------------------------
# 运维：应用注册 / 轮换 / 停用（scripts/ops/app_client.py 调用；不开放 HTTP 管理接口）
# ---------------------------------------------------------------------------


def _new_credential() -> tuple[str, str]:
    """返回 ``(client_id, secret)``；secret 仅在创建或轮换时输出一次。"""

    return f"app_{secrets.token_hex(8)}", secrets.token_urlsafe(32)


async def _require_system_config(db: Any, config_id: int, capability: str) -> None:
    row = (
        (
            await db.execute(
                text(
                    "SELECT scope,capability,is_active FROM llm_model_config WHERE id=:id"
                ),
                {"id": config_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["scope"] != "SYSTEM" or not row["is_active"]:
        raise ValueError(f"config {config_id} must be an active SYSTEM config")
    if row["capability"] != capability:
        raise ValueError(f"config {config_id} capability must be {capability}")


async def create_app_client(
    app_code: str,
    *,
    dense_config_id: int,
    sparse_config_id: int,
    description: str | None = None,
) -> tuple[str, str]:
    if not is_valid_app_code(app_code):
        raise ValueError(
            "app_code must match ^[a-z][a-z0-9_]{1,31}$ and not be 'tolink'"
        )
    client_id, secret = _new_credential()
    secret_hash = await asyncio.to_thread(hash_secret, secret)
    async with write_transaction() as db:
        await _require_system_config(db, dense_config_id, "EMBEDDING")
        await _require_system_config(db, sparse_config_id, "SPARSE_EMBEDDING")
        await db.execute(
            text(
                "INSERT INTO app_client (app_code,client_id,secret_hash,status,"
                "default_dense_config_id,default_sparse_config_id,description) "
                "VALUES (:app,:cid,:hash,'ACTIVE',:dense,:sparse,:desc)"
            ),
            {
                "app": app_code,
                "cid": client_id,
                "hash": secret_hash,
                "dense": dense_config_id,
                "sparse": sparse_config_id,
                "desc": description,
            },
        )
    audit_event("APP_CLIENT_CREATE", "success")
    return client_id, secret


async def rotate_app_secret(app_code: str) -> tuple[str, str]:
    client_id, secret = _new_credential()
    secret_hash = await asyncio.to_thread(hash_secret, secret)
    async with write_transaction() as db:
        result = await db.execute(
            text(
                "UPDATE app_client SET client_id=:cid,secret_hash=:hash WHERE app_code=:app"
            ),
            {"cid": client_id, "hash": secret_hash, "app": app_code},
        )
        if not cast(CursorResult[Any], result).rowcount:
            raise ValueError(f"app {app_code} not found")
    audit_event("APP_CLIENT_ROTATE", "success")
    return client_id, secret


async def set_app_status(app_code: str, status: str) -> None:
    if status not in {"ACTIVE", "DISABLED"}:
        raise ValueError("status must be ACTIVE or DISABLED")
    async with write_transaction() as db:
        result = await db.execute(
            text("UPDATE app_client SET status=:status WHERE app_code=:app"),
            {"status": status, "app": app_code},
        )
        if not cast(CursorResult[Any], result).rowcount:
            raise ValueError(f"app {app_code} not found")
    audit_event("APP_CLIENT_STATUS", "success")
