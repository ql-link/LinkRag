"""Java-compatible B3 admin provider and model-catalog routes."""

from typing import Annotated

from fastapi import Depends, File, Query, UploadFile
from pydantic import BaseModel, Field

from src.api.management_auth import CurrentUser, require_role
from src.api.management_http import BusinessError, ManagementRouter, success
from src.application import admin_model_catalog as catalog
from src.application.object_uploads import upload_object
from src.config import settings

router = ManagementRouter(prefix="/api/v1/admin", tags=["admin-model-catalog"])
Admin = Annotated[CurrentUser, Depends(require_role("ADMIN"))]


def _write_ready() -> None:
    if not settings.B3_CONTROL_WRITES_ENABLED:
        raise BusinessError(503, "模型目录写入尚未切流", 503)


class CreateProviderBody(BaseModel):
    providerType: str = Field(min_length=1, max_length=32)
    providerName: str = Field(min_length=1, max_length=64)
    iconUrl: str | None = Field(default=None, max_length=512)
    iconObjectKey: str | None = Field(default=None, max_length=256)
    apiBaseUrl: str = Field(min_length=1, max_length=512)
    defaultProtocol: str = Field(min_length=1, max_length=32)
    isActive: bool
    priority: int


class UpdateProviderBody(BaseModel):
    providerName: str | None = Field(default=None, max_length=64)
    iconUrl: str | None = Field(default=None, max_length=512)
    iconObjectKey: str | None = Field(default=None, max_length=256)
    apiBaseUrl: str | None = Field(default=None, max_length=512)
    defaultProtocol: str | None = Field(default=None, max_length=32)
    isActive: bool | None = None
    priority: int | None = None


class ReorderProvidersBody(BaseModel):
    providerIds: list[int] = Field(min_length=1)


class AddModelBody(BaseModel):
    modelName: str = Field(min_length=1, max_length=128)
    displayName: str | None = Field(default=None, max_length=64)
    capability: str = Field(min_length=1, max_length=32)
    protocol: str = Field(min_length=1, max_length=32)
    apiBaseUrl: str = Field(min_length=1, max_length=512)


class UpdateModelBody(BaseModel):
    modelName: str | None = Field(default=None, max_length=128)
    displayName: str | None = Field(default=None, max_length=64)
    capability: str | None = Field(default=None, max_length=32)
    protocol: str | None = Field(default=None, max_length=32)
    apiBaseUrl: str | None = Field(default=None, max_length=512)
    isActive: bool | None = None


@router.get("/providers")
async def providers(admin: Admin, page: int = Query(1, ge=1),
                    size: int = Query(10, ge=1, le=100)):
    return success(await catalog.list_providers(page, size))


@router.post("/providers")
async def create_provider(body: CreateProviderBody, admin: Admin):
    _write_ready()
    await catalog.create_provider(body.model_dump(), admin.user_id)
    return success()


@router.post("/providers/icon")
async def provider_icon(admin: Admin, file: UploadFile = File(...)):
    _write_ready()
    item = await upload_object("providerIcon", file.filename, await file.read())
    return success({"iconUrl": item.result, "iconObjectKey": item.key})


@router.patch("/providers/{provider_id}")
async def update_provider(provider_id: int, body: UpdateProviderBody, admin: Admin):
    _write_ready()
    await catalog.update_provider(provider_id, body.model_dump(exclude_unset=True), admin.user_id)
    return success()


@router.put("/providers/order")
async def reorder_providers(body: ReorderProvidersBody, admin: Admin):
    _write_ready()
    await catalog.reorder_providers(body.providerIds, admin.user_id)
    return success()


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: int, admin: Admin):
    _write_ready()
    await catalog.delete_provider(provider_id, admin.user_id)
    return success()


@router.patch("/providers/{provider_id}/active")
async def set_provider_active(provider_id: int, admin: Admin, isActive: bool):
    _write_ready()
    await catalog.set_provider_active(provider_id, isActive, admin.user_id)
    return success()


@router.get("/provider-models")
async def provider_models(
    admin: Admin, page: int = Query(1, ge=1), size: int = Query(10, ge=1, le=100),
    providerId: int | None = None, capability: str | None = None,
    isActive: bool | None = None,
):
    return success(await catalog.list_models(page, size, providerId, capability, isActive))


@router.post("/providers/{provider_id}/models")
async def add_model(provider_id: int, body: AddModelBody, admin: Admin):
    _write_ready()
    return success(await catalog.add_model(provider_id, body.model_dump(), admin.user_id))


@router.patch("/provider-models/{model_id}")
async def update_model(model_id: int, body: UpdateModelBody, admin: Admin):
    _write_ready()
    return success(await catalog.update_model(model_id, body.model_dump(exclude_unset=True),
                                              admin.user_id))


@router.patch("/provider-models/{model_id}/active")
async def set_model_active(model_id: int, admin: Admin, isActive: bool):
    _write_ready()
    await catalog.set_model_active(model_id, isActive, admin.user_id)
    return success()


@router.delete("/provider-models/{model_id}")
async def delete_model(model_id: int, admin: Admin):
    _write_ready()
    await catalog.delete_model(model_id, admin.user_id)
    return success()
