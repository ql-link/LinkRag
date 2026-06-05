"""内部召回 API 的鉴权 framework。

外部用户态 Recall API 归属 Java（复用 Sa-Token + dataset/doc 归属校验）；Python 只
暴露内部 recall runtime，校验 Java 为每次调用签发的短期内部 JWT(HS256)。本模块提供：

- ``RecallApiError``：握手前错误的统一类型，由 ``src/main.py`` 注册的异常处理器
  序列化为 ``{code, message, data}`` JSON + 对应 HTTP 状态。
- ``InternalAuthContext``：从可信 claims 解析出的请求上下文（``user_id`` 等）。
- ``verify_internal_jwt``：FastAPI 依赖，验签 + 校验 iss/aud/scope/exp，产出上下文。

设计要点见 .specs/recall-http-api/{brief,technical_design}.md。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import jwt
from fastapi import Request
from loguru import logger

from src.config import settings

# 错误码常量：与 acceptance.feature / docs/api/error_codes.md 保持一致。
CODE_UNAUTHORIZED = "RECALL_INTERNAL_UNAUTHORIZED"
CODE_USER_MISMATCH = "RECALL_USER_MISMATCH"
CODE_SCOPE_FORBIDDEN = "RECALL_SCOPE_FORBIDDEN"
CODE_INVALID_REQUEST = "RECALL_INVALID_REQUEST"
CODE_ALL_SOURCES_FAILED = "RECALL_ALL_SOURCES_FAILED"
CODE_TIMEOUT = "RECALL_TIMEOUT"
CODE_INTERNAL_ERROR = "RECALL_INTERNAL_ERROR"
# 发起用户无默认 EMBEDDING 配置：dense 召回无法编码 query，整请求硬失败。
CODE_EMBEDDING_CONFIG_MISSING = "RECALL_EMBEDDING_CONFIG_MISSING"


class RecallApiError(Exception):
    """握手前错误：携带 HTTP 状态与业务错误码。

    路由与鉴权依赖只抛本异常，由全局异常处理器统一转 JSON 响应，避免散落的
    ``HTTPException`` 破坏 ``{code, message, data}`` 响应体约定。
    """

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class InternalAuthContext:
    """从内部凭证解析出的可信请求上下文。

    Attributes:
        user_id: 来自 claims ``sub`` 的权威用户身份（正整数）。
        dataset_ids: claims 授权的数据集范围；``None`` 或空表示全库授权。
        jti: claims ``jti``，用于日志/审计/trace 关联（本期不做防重放）。
        request_id: 本次请求标识；取 ``X-Request-Id``，缺省时生成。
    """

    user_id: int
    dataset_ids: list[int] | None
    jti: str | None
    request_id: str


def _extract_bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        raise RecallApiError(401, CODE_UNAUTHORIZED, "missing internal credential")
    token = header[len("Bearer ") :].strip()
    if not token:
        raise RecallApiError(401, CODE_UNAUTHORIZED, "missing internal credential")
    return token


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-Id") or uuid4().hex


def _context_from_claims(claims: dict, request_id: str) -> InternalAuthContext:
    raw_sub = claims.get("sub")
    try:
        user_id = int(raw_sub)
    except (TypeError, ValueError):
        raise RecallApiError(401, CODE_UNAUTHORIZED, "invalid subject in credential")
    if user_id <= 0:
        raise RecallApiError(401, CODE_UNAUTHORIZED, "invalid subject in credential")

    dataset_ids = claims.get("dataset_ids")
    if dataset_ids is not None and not isinstance(dataset_ids, list):
        raise RecallApiError(401, CODE_UNAUTHORIZED, "invalid dataset_ids in credential")

    jti = claims.get("jti")
    return InternalAuthContext(
        user_id=user_id,
        dataset_ids=dataset_ids,
        jti=str(jti) if jti is not None else None,
        request_id=request_id,
    )


async def verify_internal_jwt(request: Request) -> InternalAuthContext:
    """FastAPI 依赖：校验内部 JWT，产出 ``InternalAuthContext``。

    校验顺序：取 Bearer token → HS256 验签 + iss/aud/exp（PyJWT 内置）→ scope（手动）
    → sub→user_id。任一失败抛 ``RecallApiError(401, RECALL_INTERNAL_UNAUTHORIZED)``。

    ``RECALL_INTERNAL_AUTH_ENABLED=False``（仅本地联调）时跳过验签，但仍要求携带
    token 以解析身份；生产环境必须保持开启。
    """
    request_id = _request_id(request)
    token = _extract_bearer_token(request)

    if not settings.RECALL_INTERNAL_AUTH_ENABLED:
        # 本地联调：不验签，仅解析 claims 取身份。生产恒开启，不会走到这里。
        logger.warning(
            "[recall] internal auth disabled; skipping JWT verification request_id={}",
            request_id,
        )
        claims = jwt.decode(token, options={"verify_signature": False})
        return _context_from_claims(claims, request_id)

    try:
        claims = jwt.decode(
            token,
            settings.RECALL_INTERNAL_JWT_SECRET,
            algorithms=["HS256"],
            audience=settings.RECALL_INTERNAL_JWT_AUDIENCE,
            issuer=settings.RECALL_INTERNAL_JWT_ISSUER,
            options={"require": ["exp"]},
        )
    except jwt.PyJWTError as exc:
        logger.info("[recall] internal JWT rejected request_id={}: {}", request_id, exc)
        raise RecallApiError(401, CODE_UNAUTHORIZED, "invalid or expired credential")

    if claims.get("scope") != settings.RECALL_INTERNAL_JWT_SCOPE:
        raise RecallApiError(401, CODE_UNAUTHORIZED, "credential scope not permitted")

    return _context_from_claims(claims, request_id)
