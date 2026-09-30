"""接入应用 ``/api/v1/apps/*`` 的鉴权依赖。

只接受应用凭证 ``Authorization: Bearer <client_id>.<secret>`` 与 ``X-App-User-Id``；
不接受 Web access token。``X-App-User-Id`` 仅在凭证校验通过后才被信任，且只能解析为
本应用命名空间内的影子用户。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from src.api.management_http import BusinessError

from src.application.app_identity import (
    AppClient,
    AppIdentityError,
    resolve_shadow_user,
    verify_app_credential,
)
from src.application.recall_errors import _request_id
from src.config import settings


@dataclass(frozen=True, slots=True)
class AppPrincipal:
    """应用鉴权后的可信调用方：影子用户即全部下游隔离的 ``user_id``。"""

    app: AppClient
    user_id: int
    default_dataset_id: int | None
    request_id: str

    @property
    def app_code(self) -> str:
        return self.app.app_code


def require_apps_api_enabled() -> None:
    if not settings.APPS_API_ENABLED:
        raise HTTPException(status_code=404, detail="Not Found")


def _bearer(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise AppIdentityError(401, "APP_CREDENTIAL_INVALID", "missing app credential")
    return header[len("Bearer ") :].strip()


async def require_app_principal(request: Request) -> AppPrincipal:
    require_apps_api_enabled()
    try:
        app = await verify_app_credential(_bearer(request))
        shadow = await resolve_shadow_user(app, request.headers.get("X-App-User-Id"))
    except AppIdentityError as exc:
        # 与 /apps/* 的 ManagementRoute 响应体一致：{code:<HTTP 状态>, message, data:{reason}}。
        raise BusinessError(
            exc.status_code, exc.message, exc.status_code, data={"reason": exc.code}
        ) from exc
    return AppPrincipal(
        app=app,
        user_id=shadow.user_id,
        default_dataset_id=shadow.default_dataset_id,
        request_id=_request_id(request),
    )
