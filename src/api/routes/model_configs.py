"""User-facing B3 model catalog and configuration routes."""

from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, Field

from src.api.management_auth import CurrentUser, require_login
from src.api.management_http import BusinessError, ManagementRouter, success
from src.application import model_configs
from src.config import settings

router = ManagementRouter(prefix="/api/v1/llm", tags=["model-configs"])


def _write_ready() -> None:
    if not settings.B3_CONTROL_WRITES_ENABLED:
        raise BusinessError(503, "模型配置写入尚未切流", 503)


class SetupProviderBody(BaseModel):
    providerType: str = Field(min_length=1, max_length=32)
    apiKey: str = Field(min_length=1, max_length=512)


class SetDefaultBody(BaseModel):
    configId: int = Field(gt=0)


class ChangeActiveBody(BaseModel):
    isActive: bool


class EmergencyDisableBody(BaseModel):
    confirmed: bool


@router.get("/providers")
async def providers(
    user: Annotated[CurrentUser, Depends(require_login)],
    capability: str | None = None,
):
    return success(await model_configs.list_provider_catalog(capability))


@router.get("/configs")
async def configs(
    user: Annotated[CurrentUser, Depends(require_login)],
    providerType: str | None = None,
    capability: str | None = None,
    isActive: bool | None = None,
):
    return success(
        await model_configs.list_visible_configs(
            user.user_id, provider_type=providerType, capability=capability, is_active=isActive
        )
    )


@router.post("/configs/setup-provider")
async def setup_provider(
    user: Annotated[CurrentUser, Depends(require_login)], body: SetupProviderBody
):
    _write_ready()
    return success(await model_configs.setup_provider(user.user_id, body.providerType, body.apiKey))


@router.patch("/configs/{config_id}/active")
async def change_active(
    config_id: int,
    body: ChangeActiveBody,
    user: Annotated[CurrentUser, Depends(require_login)],
):
    _write_ready()
    await model_configs.change_active(user.user_id, config_id, body.isActive)
    return success()


@router.post("/configs/{config_id}/emergency-disable")
async def emergency_disable(
    config_id: int,
    body: EmergencyDisableBody,
    user: Annotated[CurrentUser, Depends(require_login)],
):
    _write_ready()
    await model_configs.change_active(
        user.user_id, config_id, False, emergency=True, confirmed=body.confirmed
    )
    return success()


@router.delete("/configs/{config_id}")
async def delete_config(
    config_id: int,
    user: Annotated[CurrentUser, Depends(require_login)],
):
    _write_ready()
    await model_configs.delete_config(user.user_id, config_id)
    return success()


@router.get("/defaults")
async def defaults(user: Annotated[CurrentUser, Depends(require_login)]):
    return success(await model_configs.list_defaults(user.user_id))


@router.get("/defaults/{capability}")
async def get_default(capability: str, user: Annotated[CurrentUser, Depends(require_login)]):
    return success(await model_configs.get_default(user.user_id, capability))


@router.put("/defaults/{capability}")
async def set_default(
    capability: str,
    body: SetDefaultBody,
    user: Annotated[CurrentUser, Depends(require_login)],
):
    _write_ready()
    return success(await model_configs.set_default(user.user_id, capability, body.configId))


@router.delete("/defaults/{capability}")
async def clear_default(capability: str, user: Annotated[CurrentUser, Depends(require_login)]):
    _write_ready()
    return success(await model_configs.clear_default(user.user_id, capability))
