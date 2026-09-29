"""Java-compatible B1 auth, profile and admin-user HTTP routes."""

from __future__ import annotations

import asyncio
from pathlib import PurePath
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, File, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api.management_auth import CurrentUser, require_login, require_role
from src.api.management_http import BusinessError, ManagementRouter, success
from src.application.identity_session import HybridSessionState
from src.application.identity_users import CacheInvalidationError, IdentityUsers
from src.application.object_uploads import upload_object, validate_upload
from src.config import settings
from src.services.storage.factory import StorageFactory

auth_router = ManagementRouter(prefix="/api/v1/auth", tags=["auth"])
user_router = ManagementRouter(prefix="/api/v1/user", tags=["user"])
admin_router = ManagementRouter(prefix="/api/v1/admin", tags=["admin-users"])


class LoginRequest(BaseModel):
    account: str = Field(min_length=1)
    password: str = Field(min_length=1)

    @field_validator("account", "password", mode="before")
    @classmethod
    def coerce_json_scalar(cls, value: object) -> object:
        # Jackson 将 JSON 数字/布尔值读入 Java String 字段；数组和对象仍应拒绝。
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, (int, float)):
            return str(value)
        return value

    @field_validator("account", "password")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("不能为空")
        return value


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    email: str = Field(min_length=3, max_length=128, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @field_validator("username", "password", "email", mode="before")
    @classmethod
    def coerce_json_scalar(cls, value: object) -> object:
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, (int, float)):
            return str(value)
        return value

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        # Java @Size 校验原始输入，AuthServiceImpl 随后才 trim。
        if not value.strip():
            raise ValueError("用户名不能为空")
        return value.strip()

    @field_validator("password")
    @classmethod
    def reject_blank_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("密码不能为空")
        return value


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    nickname: str | None = None
    email: str | None = None
    phone: str | None = None
    avatar_url: str | None = Field(default=None, alias="avatarUrl")
    bio: str | None = Field(default=None, max_length=200)
    team: str | None = Field(default=None, max_length=64)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    current_password: str = Field(min_length=1, max_length=128, alias="currentPassword")
    new_password: str = Field(min_length=8, max_length=128, alias="newPassword")

    @field_validator("new_password")
    @classmethod
    def reject_blank_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("新密码不能为空")
        return value


class UpdateStatusRequest(BaseModel):
    status: int = Field(ge=0, le=1)


class UpdateRoleRequest(BaseModel):
    role: str = Field(pattern="^(ADMIN|USER)$")


def _sessions(request: Request) -> HybridSessionState:
    sessions = getattr(request.app.state, "identity_sessions", None)
    if sessions is None:
        raise BusinessError(503, "登录状态暂不可验证", 503)
    return sessions


def _users(request: Request) -> IdentityUsers:
    return IdentityUsers(_sessions(request))


def _issuer_ready() -> None:
    if not (
        settings.B1_PYTHON_ISSUER_ENABLED
        and settings.B1_JAVA_PROTECTED_ROUTES_RETIRED
        and settings.B1_ACCESS_JWT_PRIVATE_KEY_PATH
    ):
        raise BusinessError(503, "Python 登录签发尚未启用", 503)


@auth_router.post("/login")
async def login(request: Request, body: LoginRequest):
    _issuer_ready()
    return success(await _users(request).login(body.account, body.password))


@auth_router.post("/register")
async def register(request: Request, body: RegisterRequest):
    _issuer_ready()
    return success(await _users(request).register(body.username, body.password, body.email))


@auth_router.post("/logout")
async def logout(request: Request):
    token = request.headers.get("satoken")
    if not token:
        return success()
    authenticator = getattr(request.app.state, "management_authenticator", None)
    if authenticator is None:
        raise BusinessError(503, "管理端认证尚未配置", 503)
    try:
        claims = authenticator._verifier.verify(token)
    except BusinessError as exc:
        if exc.http_status == 401:
            # 与 Java StpUtil.logout() 一致：无效/过期 token 登出为幂等成功。
            return success()
        raise
    try:
        await _sessions(request).revoke(token, claims)
    except Exception as exc:
        raise BusinessError(503, "登录状态暂无法注销", 503) from exc
    return success()


def _verified_claims(request: Request):
    """已通过 require_login 的请求：取出当前令牌及其声明，供续期 / 改密撤销旧令牌。"""
    token = request.headers.get("satoken") or ""
    authenticator = getattr(request.app.state, "management_authenticator", None)
    if authenticator is None:
        raise BusinessError(503, "管理端认证尚未配置", 503)
    return token, authenticator._verifier.verify(token)


@auth_router.post("/refresh")
async def refresh(request: Request, user: Annotated[CurrentUser, Depends(require_login)]):
    _issuer_ready()
    token, claims = _verified_claims(request)
    return success(await _users(request).refresh(token, claims))


@user_router.post("/password")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    user: Annotated[CurrentUser, Depends(require_login)],
):
    _issuer_ready()
    token, claims = _verified_claims(request)
    return success(
        await _users(request).change_password(
            token, claims, body.current_password, body.new_password
        )
    )


@user_router.get("/profile")
async def profile(request: Request, user: Annotated[CurrentUser, Depends(require_login)]):
    return success(await _users(request).profile(user.user_id))


@user_router.patch("/profile")
async def update_profile(
    request: Request,
    body: UpdateProfileRequest,
    user: Annotated[CurrentUser, Depends(require_login)],
):
    await _users(request).update_profile(
        user.user_id, body.model_dump(by_alias=True, exclude_unset=True)
    )
    return success()


_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
_AVATAR_MAX_BYTES = 5 * 1024 * 1024


@user_router.post("/avatar")
async def upload_avatar(
    request: Request,
    user: Annotated[CurrentUser, Depends(require_login)],
    file: UploadFile = File(...),
):
    content = await file.read(_AVATAR_MAX_BYTES + 1)
    if not content:
        raise BusinessError(40001, "请选择要上传的文件", 400)
    validate_upload("avatar", file.filename, content)
    suffix = PurePath(file.filename or "").suffix.lower()
    key = f"avatar/{user.user_id}/{uuid4().hex}{suffix}"
    bucket = settings.MINIO_PUBLIC_BUCKET
    storage = StorageFactory.get_storage()
    uploaded = await upload_object(
        "avatar",
        file.filename,
        content,
        _IMAGE_MIME[suffix],
        object_key=key,
        storage=storage,
    )
    url = uploaded.result
    try:
        updated = await _users(request).set_avatar(user.user_id, url)
    except CacheInvalidationError:
        # 数据库已提交且指向新对象，不能把仍被引用的头像删除。
        raise
    except Exception:
        await asyncio.to_thread(storage.remove_object, bucket, key)
        raise
    return success(updated)


@admin_router.get("/users")
async def list_users(
    request: Request,
    user: Annotated[CurrentUser, Depends(require_role("ADMIN"))],
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
):
    return success(await _users(request).list_users(page, size))


@admin_router.patch("/users/{user_id}/status")
async def update_user_status(
    request: Request,
    user_id: int,
    body: UpdateStatusRequest,
    actor: Annotated[CurrentUser, Depends(require_role("ADMIN"))],
):
    if not settings.B1_JAVA_PROTECTED_ROUTES_RETIRED:
        raise BusinessError(503, "Java 路由仍在使用，暂不可从 Python 修改账号状态", 503)
    await _users(request).update_admin_field(actor.user_id, user_id, "status", body.status)
    return success()


@admin_router.patch("/users/{user_id}/role")
async def update_user_role(
    request: Request,
    user_id: int,
    body: UpdateRoleRequest,
    actor: Annotated[CurrentUser, Depends(require_role("ADMIN"))],
):
    await _users(request).update_admin_field(actor.user_id, user_id, "role", body.role)
    return success()
