"""LLM 目录/展示查询，始终直读 MySQL，不访问 runtime cache。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.db_models import LLMModelConfigDB, SystemProviderDB


class LLMCatalogReader:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_system_providers(self, provider_type: str | None = None) -> list[dict[str, Any]]:
        stmt = (
            select(SystemProviderDB)
            .options(selectinload(SystemProviderDB.provider_models))
            .where(SystemProviderDB.is_active.is_(True))
        )
        if provider_type:
            stmt = stmt.where(SystemProviderDB.provider_type == provider_type)
        result = await self._db.execute(stmt.order_by(SystemProviderDB.priority.desc()))
        items: list[dict[str, Any]] = []
        for provider in result.scalars().all():
            models: dict[str, list[str]] = {}
            options: dict[str, dict[str, Any]] = {}
            for model in provider.provider_models:
                if not model.is_active:
                    continue
                models.setdefault(model.model_name, []).append(model.capability)
                option = options.setdefault(
                    model.model_name,
                    {
                        "model_name": model.model_name,
                        "display_name": model.display_name or model.model_name,
                        "capabilities": [],
                        "protocol": model.protocol,
                        "api_base_url": model.api_base_url,
                    },
                )
                option["capabilities"].append(model.capability)
            items.append(
                {
                    "provider_type": provider.provider_type,
                    "provider_name": provider.provider_name,
                    "api_base_url": provider.api_base_url,
                    "models": models,
                    "model_options": list(options.values()),
                    "is_active": provider.is_active,
                }
            )
        return items

    async def get_visible_configs(self, user_id: int) -> list[dict[str, Any]]:
        result = await self._db.execute(
            select(LLMModelConfigDB)
            .where(
                or_(
                    (LLMModelConfigDB.scope == "SYSTEM")
                    & (LLMModelConfigDB.owner_user_id == 0),
                    (LLMModelConfigDB.scope == "USER")
                    & (LLMModelConfigDB.owner_user_id == int(user_id)),
                )
            )
            .order_by(LLMModelConfigDB.id.desc())
        )
        return [
            {
                "configId": row.id,
                "scope": row.scope,
                "providerId": row.provider_id,
                "providerType": row.provider_type,
                "modelName": row.model_name,
                "displayName": row.display_name or row.model_name,
                "capability": row.capability,
                "protocol": row.protocol,
                "apiBaseUrl": row.api_base_url,
                "isActive": row.is_active,
                "editable": row.scope == "USER" and row.owner_user_id == int(user_id),
                "snapshotVersion": row.snapshot_version,
                "apiKeyCiphertext": row.api_key,
            }
            for row in result.scalars().all()
        ]
