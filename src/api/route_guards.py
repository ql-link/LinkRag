"""非用户会话类路由的访问门禁。

- ``require_internal_service_token``：服务端到服务端调用，校验 ``INTERNAL_API_TOKEN``；
  未配置时 fail-closed，任何请求都拒绝。
- ``require_debug_endpoints_enabled``：联调 / 调试入口开关，关闭时返回 404，
  不暴露路由存在性。调试入口在开关之外仍需叠加 ADMIN 鉴权。
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request

from src.config import settings


def require_internal_service_token(request: Request) -> None:
    """校验 ``Authorization: Bearer <INTERNAL_API_TOKEN>``，常量时间比较。"""

    expected = settings.INTERNAL_API_TOKEN
    authorization = request.headers.get("Authorization", "")
    if not expected or not secrets.compare_digest(authorization, "Bearer " + expected):
        raise HTTPException(status_code=401, detail="service authentication failed")


def require_debug_endpoints_enabled() -> None:
    """``DEBUG_ENDPOINTS_ENABLED=false`` 时按不存在的路由处理。"""

    if not settings.DEBUG_ENDPOINTS_ENABLED:
        raise HTTPException(status_code=404, detail="Not Found")
