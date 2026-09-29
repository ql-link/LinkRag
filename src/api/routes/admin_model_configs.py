"""Admin B3 SYSTEM model configuration routes with database-backed role checks."""

from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, Field

from src.api.management_auth import CurrentUser, require_role
from src.api.management_http import BusinessError, ManagementRouter, success
from src.application import model_configs
from src.config import settings

router = ManagementRouter(prefix="/api/v1/admin/llm", tags=["admin-model-configs"])


def _write_ready() -> None:
    if not settings.B3_CONTROL_WRITES_ENABLED:
        raise BusinessError(503, "模型配置写入尚未切流", 503)


class CatalogMutation(BaseModel):
    providerId: int = Field(gt=0)
    modelName: str = Field(min_length=1, max_length=128)
    displayName: str | None = Field(default=None, max_length=64)
    capability: str = Field(min_length=1)
    protocol: str = Field(min_length=1)
    apiBaseUrl: str = Field(min_length=1, max_length=512)


class SaveConfigBody(BaseModel):
    sourceProviderModelId: int | None = Field(default=None, gt=0)
    catalogMutation: CatalogMutation | None = None
    apiKey: str | None = Field(default=None, max_length=512)


class ActiveBody(BaseModel):
    isActive: bool


class EmergencyBody(BaseModel):
    confirmed: bool | None = None


@router.get("/configs")
async def configs(
    admin: Annotated[CurrentUser, Depends(require_role("ADMIN"))],
    capability: str | None = None,
    isActive: bool | None = None,
):
    return success(
        await model_configs.list_visible_configs(
            admin.user_id, capability=capability, is_active=isActive, system_only=True
        )
    )


@router.post("/configs")
async def create(
    body: SaveConfigBody,
    admin: Annotated[CurrentUser, Depends(require_role("ADMIN"))],
):
    _write_ready()
    return success(
        await model_configs.save_system_config(admin.user_id, body.model_dump(exclude_none=True))
    )


@router.put("/configs/{config_id}")
async def update(
    config_id: int,
    body: SaveConfigBody,
    admin: Annotated[CurrentUser, Depends(require_role("ADMIN"))],
):
    _write_ready()
    return success(
        await model_configs.save_system_config(
            admin.user_id, body.model_dump(exclude_none=True), config_id=config_id
        )
    )


@router.patch("/configs/{config_id}/active")
async def change_active(
    config_id: int,
    body: ActiveBody,
    admin: Annotated[CurrentUser, Depends(require_role("ADMIN"))],
):
    _write_ready()
    await model_configs.change_active(admin.user_id, config_id, body.isActive, admin=True)
    return success()


@router.post("/configs/{config_id}/emergency-disable")
async def emergency_disable(
    config_id: int,
    body: EmergencyBody,
    admin: Annotated[CurrentUser, Depends(require_role("ADMIN"))],
):
    _write_ready()
    await model_configs.change_active(
        admin.user_id,
        config_id,
        False,
        admin=True,
        emergency=True,
        confirmed=bool(body.confirmed),
    )
    return success()


@router.delete("/configs/{config_id}")
async def delete(
    config_id: int,
    admin: Annotated[CurrentUser, Depends(require_role("ADMIN"))],
):
    _write_ready()
    await model_configs.delete_config(admin.user_id, config_id, admin=True)
    return success()
