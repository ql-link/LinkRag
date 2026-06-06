"""对外直连召回 SSE（LINK-40）的会话鉴权与并发治理。

外部用户态 Recall 入口归属 Java：Java 用 Sa-Token 鉴权并校验 dataset 归属后，签发
**短期 session token**；前端凭该 token 直连 Python ``POST /api/v1/recall/stream``。
本模块提供：

- ``SessionAuthContext``：从可信 claims 解析出的请求上下文；
- ``verify_session_token``：FastAPI 依赖，用**独立密钥**验签 + 校验 iss/aud/scope/exp；
- ``acquire_stream_slot`` / ``release_stream_slot``：按 ``user_id`` 的并发流计数。

与内部端点（``internal_auth.py``）的关键差异：面向浏览器、密钥/受众独立；token
**短期可复用**——只校验 ``exp``，不做一次性消费 / 防重放 / 撤销，资源滥用由并发上限封顶。
设计依据见 .specs/recall-direct-sse/{brief,technical_design}.md。
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Request
from loguru import logger

from src.api.internal_auth import (
    CODE_SESSION_UNAUTHORIZED,
    RecallApiError,
    _request_id,
)
from src.cache.redis_client import redis_client
from src.config import settings

# 并发计数 key 前缀；按 user_id 分桶，跨 worker / 实例共享。
_CONCURRENT_KEY_PREFIX = "recall:concurrent:"


@dataclass(frozen=True)
class SessionAuthContext:
    """从 session token claims 解析出的可信请求上下文。

    Attributes:
        user_id: 来自 claims ``sub`` 的权威用户身份（正整数）。
        dataset_ids: claims 授权的数据集范围；``None`` 或空表示全库授权。
        request_id: 本次请求标识；取 ``X-Request-Id``，缺省时生成。
    """

    user_id: int
    dataset_ids: list[int] | None
    request_id: str


def _extract_session_token(request: Request) -> str:
    """从 ``Authorization: Bearer`` 提取 session token。

    缺失或格式不符抛 ``RECALL_SESSION_UNAUTHORIZED``（区别于内部端点的错误码）。
    """
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        raise RecallApiError(401, CODE_SESSION_UNAUTHORIZED, "missing session credential")
    token = header[len("Bearer ") :].strip()
    if not token:
        raise RecallApiError(401, CODE_SESSION_UNAUTHORIZED, "missing session credential")
    return token


def _context_from_session_claims(claims: dict, request_id: str) -> SessionAuthContext:
    """从可信 claims 装配上下文；身份只取 claims，不信任前端自报。"""
    raw_sub = claims.get("sub")
    try:
        user_id = int(raw_sub)
    except (TypeError, ValueError):
        raise RecallApiError(401, CODE_SESSION_UNAUTHORIZED, "invalid subject in credential")
    if user_id <= 0:
        raise RecallApiError(401, CODE_SESSION_UNAUTHORIZED, "invalid subject in credential")

    dataset_ids = claims.get("dataset_ids")
    if dataset_ids is not None and not isinstance(dataset_ids, list):
        raise RecallApiError(
            401, CODE_SESSION_UNAUTHORIZED, "invalid dataset_ids in credential"
        )

    return SessionAuthContext(
        user_id=user_id, dataset_ids=dataset_ids, request_id=request_id
    )


async def verify_session_token(request: Request) -> SessionAuthContext:
    """FastAPI 依赖：校验 Java 签发的 session token，产出 ``SessionAuthContext``。

    校验链（任一失败 → ``RecallApiError(401, RECALL_SESSION_UNAUTHORIZED)``）：
    Bearer token → HS256 验签（**独立 session 密钥**）+ iss/aud/exp（PyJWT 内置）
    → scope（手动）→ sub→user_id。token 短期可复用，无一次性消费步骤——有效期内重复
    建连均放行（断线重连可复用未过期 token）。

    ``RECALL_SESSION_AUTH_ENABLED=False`` 仅本地联调：跳过验签但仍解析 claims 取身份；
    生产恒开启。
    """
    request_id = _request_id(request)
    token = _extract_session_token(request)

    if not settings.RECALL_SESSION_AUTH_ENABLED:
        # 本地联调：不验签，仅解析 claims 取身份。生产恒开启，不会走到这里。
        logger.warning(
            "[recall-session] auth disabled; skipping JWT verification request_id={}",
            request_id,
        )
        claims = jwt.decode(token, options={"verify_signature": False})
        return _context_from_session_claims(claims, request_id)

    try:
        claims = jwt.decode(
            token,
            settings.RECALL_SESSION_JWT_SECRET,
            algorithms=["HS256"],
            audience=settings.RECALL_SESSION_JWT_AUDIENCE,
            issuer=settings.RECALL_SESSION_JWT_ISSUER,
            options={"require": ["exp"]},
        )
    except jwt.PyJWTError as exc:
        logger.info("[recall-session] JWT rejected request_id={}: {}", request_id, exc)
        raise RecallApiError(401, CODE_SESSION_UNAUTHORIZED, "invalid or expired credential")

    if claims.get("scope") != settings.RECALL_SESSION_JWT_SCOPE:
        raise RecallApiError(401, CODE_SESSION_UNAUTHORIZED, "credential scope not permitted")

    return _context_from_session_claims(claims, request_id)


def _concurrent_key(user_id: int) -> str:
    return f"{_CONCURRENT_KEY_PREFIX}{user_id}"


async def acquire_stream_slot(user_id: int) -> bool:
    """占用一个并发流名额；返回是否成功（False → 调用方应回 429）。

    INCR 先占位再判断，保证多 worker 下不超卖；超过上限则 DECR 回退。key 设
    ``2×stream_timeout`` 安全 TTL，兜底进程异常退出未 release 造成的名额泄漏。

    Redis 不可用时 **fail-open**（放行 + 告警）：去一次性后 Redis 仅做资源保护、不再
    承载安全语义，短暂失去并发限流好于阻断全部召回。
    """
    key = _concurrent_key(user_id)
    safety_ttl = max(1, settings.RECALL_STREAM_TIMEOUT_MS // 1000 * 2)
    try:
        count = await redis_client.incr(key)
        await redis_client.expire(key, safety_ttl)
    except Exception:  # noqa: BLE001 - Redis 故障不阻断召回，fail-open
        logger.warning(
            "[recall-session] redis unavailable on acquire, fail-open user_id={}", user_id
        )
        return True

    if count > settings.RECALL_SESSION_MAX_CONCURRENT:
        # 超卖，回退占位并拒绝。
        try:
            await redis_client.decr(key)
        except Exception:  # noqa: BLE001 - 回退失败由 TTL 兜底
            logger.warning("[recall-session] redis decr failed on rollback user_id={}", user_id)
        return False
    return True


async def release_stream_slot(user_id: int) -> None:
    """释放一个并发流名额；在流结束 / 断连的 finally 中调用。

    DECR 后若计数为负（异常路径下的重复释放），重置回 0，避免计数漂移把后续请求误放行。
    Redis 故障静默忽略，由 key 的安全 TTL 兜底回收。
    """
    key = _concurrent_key(user_id)
    try:
        remaining = await redis_client.decr(key)
        if remaining < 0:
            await redis_client.set(key, "0")
    except Exception:  # noqa: BLE001 - 释放失败由 TTL 兜底，不影响主流程
        logger.warning("[recall-session] redis unavailable on release user_id={}", user_id)
