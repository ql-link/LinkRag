"""B3 admin catalog operations over the existing provider/model tables."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from src.api.management_http import BusinessError
from src.application.model_configs import _PROTOCOLS, normalize_capability
from src.database import get_db_context, write_transaction
from src.observability.audit import audit_event


def _provider(row: dict) -> dict:
    return {
        "id": int(row["id"]),
        "providerType": row["provider_type"],
        "providerName": row["provider_name"],
        "iconUrl": row["icon_url"],
        "iconObjectKey": row["icon_object_key"],
        "apiBaseUrl": row["api_base_url"],
        "defaultProtocol": row["default_protocol"],
        "isActive": bool(row["is_active"]),
        "priority": int(row["priority"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _model(row: dict) -> dict:
    return {
        "id": int(row["id"]),
        "providerId": int(row["provider_id"]),
        "modelName": row["model_name"],
        "displayName": row["display_name"],
        "capability": row["capability"],
        "protocol": row["protocol"],
        "apiBaseUrl": row["api_base_url"],
        "isActive": bool(row["is_active"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _page(items: list[dict], total: int, page: int, size: int) -> dict:
    return {
        "items": items,
        "total": total,
        "page": page,
        "pageSize": size,
        "totalPages": (total + size - 1) // size,
    }


def _protocol(value: str | None) -> str:
    if value is None or value not in _PROTOCOLS:
        raise BusinessError(10015, "协议不在支持范围内", 400)
    return value


async def list_providers(page: int, size: int) -> dict:
    async with get_db_context() as db:
        total = int(
            (await db.execute(text("SELECT COUNT(*) FROM llm_system_provider"))).scalar_one()
        )
        rows = (
            (
                await db.execute(
                    text(
                        "SELECT * FROM llm_system_provider "
                        "ORDER BY priority DESC,id LIMIT :size OFFSET :offset"
                    ),
                    {"size": size, "offset": (page - 1) * size},
                )
            )
            .mappings()
            .all()
        )
    return _page([_provider(dict(row)) for row in rows], total, page, size)


async def _require_provider(db, provider_id: int) -> dict:
    row = (
        (
            await db.execute(
                text("SELECT * FROM llm_system_provider WHERE id=:id FOR UPDATE"),
                {"id": provider_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise BusinessError(10001, "系统厂商不存在", 404)
    return dict(row)


async def _require_active_model(db, provider_id: int) -> None:
    count = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM llm_provider_model " "WHERE provider_id=:pid AND is_active=1"
            ),
            {"pid": provider_id},
        )
    ).scalar_one()
    if not count:
        raise BusinessError(10019, "启用厂商前至少需要上架一个模型", 400)


async def create_provider(body: dict, actor_id: int) -> None:
    _protocol(body["defaultProtocol"])
    if body["isActive"]:
        raise BusinessError(10019, "启用厂商前至少需要上架一个模型", 400)
    try:
        async with write_transaction() as db:
            await db.execute(
                text("""
                INSERT INTO llm_system_provider
                  (provider_type,provider_name,icon_url,icon_object_key,api_base_url,
                   default_protocol,is_active,priority)
                VALUES(:type,:name,:icon,:key,:url,:protocol,:active,:priority)
            """),
                {
                    "type": body["providerType"],
                    "name": body["providerName"],
                    "icon": body.get("iconUrl"),
                    "key": body.get("iconObjectKey"),
                    "url": body["apiBaseUrl"],
                    "protocol": body["defaultProtocol"],
                    "active": False,
                    "priority": body["priority"],
                },
            )
    except IntegrityError as exc:
        raise BusinessError(10007, "厂商类型已存在", 400) from exc
    audit_event("PROVIDER_CREATE", "success", actor_id=actor_id)


async def update_provider(provider_id: int, body: dict, actor_id: int) -> None:
    columns = {
        "providerName": "provider_name",
        "iconUrl": "icon_url",
        "iconObjectKey": "icon_object_key",
        "apiBaseUrl": "api_base_url",
        "defaultProtocol": "default_protocol",
        "isActive": "is_active",
        "priority": "priority",
    }
    values: dict = {}
    for name, column in columns.items():
        value = body.get(name)
        if value is None:
            continue
        if name in {"providerName", "apiBaseUrl", "defaultProtocol"} and not str(value).strip():
            continue
        if name in {"iconUrl", "iconObjectKey"}:
            value = str(value).strip() or None
        if name == "defaultProtocol":
            value = _protocol(value)
        values[column] = value
    async with write_transaction() as db:
        await _require_provider(db, provider_id)
        if values.get("is_active"):
            await _require_active_model(db, provider_id)
        if values:
            assignments = ",".join(f"{column}=:{column}" for column in values)
            await db.execute(
                text(f"UPDATE llm_system_provider SET {assignments} WHERE id=:id"),
                {**values, "id": provider_id},
            )
    audit_event("PROVIDER_UPDATE", "success", actor_id=actor_id, target_id=provider_id)


async def reorder_providers(provider_ids: list[int], actor_id: int) -> None:
    if not provider_ids or len(provider_ids) != len(set(provider_ids)):
        raise BusinessError(400, "厂商排序不能为空或包含重复 ID", 400)
    async with write_transaction() as db:
        rows = (
            (await db.execute(text("SELECT id FROM llm_system_provider FOR UPDATE")))
            .scalars()
            .all()
        )
        if set(rows) != set(provider_ids):
            raise BusinessError(400, "厂商排序必须包含全部有效厂商", 400)
        priority = len(provider_ids) * 10
        for provider_id in provider_ids:
            await db.execute(
                text("UPDATE llm_system_provider SET priority=:priority " "WHERE id=:id"),
                {"priority": priority, "id": provider_id},
            )
            priority -= 10
    audit_event("PROVIDER_REORDER", "success", actor_id=actor_id)


async def delete_provider(provider_id: int, actor_id: int) -> None:
    async with write_transaction() as db:
        await _require_provider(db, provider_id)
        await db.execute(text("DELETE FROM llm_system_provider WHERE id=:id"), {"id": provider_id})
    audit_event("PROVIDER_DELETE", "success", actor_id=actor_id, target_id=provider_id)


async def set_provider_active(provider_id: int, active: bool, actor_id: int) -> None:
    async with write_transaction() as db:
        await _require_provider(db, provider_id)
        if active:
            await _require_active_model(db, provider_id)
        await db.execute(
            text("UPDATE llm_system_provider SET is_active=:active WHERE id=:id"),
            {"active": active, "id": provider_id},
        )
    audit_event("PROVIDER_ACTIVE", "success", actor_id=actor_id, target_id=provider_id)


async def list_models(
    page: int,
    size: int,
    provider_id: int | None,
    capability: str | None,
    is_active: bool | None,
) -> dict:
    clauses = []
    params: dict = {"size": size, "offset": (page - 1) * size}
    if provider_id is not None:
        clauses.append("provider_id=:pid")
        params["pid"] = provider_id
    if capability and capability.strip():
        clauses.append("capability=:cap")
        params["cap"] = normalize_capability(capability)
    if is_active is not None:
        clauses.append("is_active=:active")
        params["active"] = is_active
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    async with get_db_context() as db:
        total = int(
            (
                await db.execute(text("SELECT COUNT(*) FROM llm_provider_model" + where), params)
            ).scalar_one()
        )
        rows = (
            (
                await db.execute(
                    text(
                        "SELECT * FROM llm_provider_model"
                        + where
                        + " ORDER BY provider_id,model_name,capability "
                        "LIMIT :size OFFSET :offset"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
    return _page([_model(dict(row)) for row in rows], total, page, size)


async def _require_model(db, model_id: int) -> dict:
    row = (
        (
            await db.execute(
                text("SELECT * FROM llm_provider_model WHERE id=:id FOR UPDATE"), {"id": model_id}
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise BusinessError(10008, "模型目录项不存在", 404)
    return dict(row)


async def add_model(provider_id: int, body: dict, actor_id: int) -> dict:
    cap = normalize_capability(body["capability"])
    protocol = _protocol(body["protocol"])
    if not body["apiBaseUrl"].strip():
        raise BusinessError(10014, "模型能力缺少协议或入口，无法保存或展开", 400)
    async with write_transaction() as db:
        await _require_provider(db, provider_id)
        result = await db.execute(
            text("""
            INSERT INTO llm_provider_model
              (provider_id,model_name,display_name,capability,protocol,api_base_url,is_active)
            VALUES(:pid,:name,:display,:cap,:protocol,:url,1)
            ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id),
              display_name=VALUES(display_name),protocol=VALUES(protocol),
              api_base_url=VALUES(api_base_url),is_active=1
        """),
            {
                "pid": provider_id,
                "name": body["modelName"],
                "display": (body.get("displayName") or "").strip() or None,
                "cap": cap,
                "protocol": protocol,
                "url": body["apiBaseUrl"],
            },
        )
        row = await _require_model(db, int(cast(CursorResult[Any], result).lastrowid))
    audit_event("PROVIDER_MODEL_SAVE", "success", actor_id=actor_id, target_id=row["id"])
    return _model(row)


async def update_model(model_id: int, body: dict, actor_id: int) -> dict:
    columns = {
        "modelName": "model_name",
        "displayName": "display_name",
        "capability": "capability",
        "protocol": "protocol",
        "apiBaseUrl": "api_base_url",
        "isActive": "is_active",
    }
    values: dict = {}
    for name, column in columns.items():
        value = body.get(name)
        if value is None:
            continue
        if name in {"modelName", "capability", "protocol", "apiBaseUrl"} and not str(value).strip():
            continue
        if name == "displayName":
            value = value.strip() or None
        if name == "capability":
            value = normalize_capability(value)
        if name == "protocol":
            value = _protocol(value)
        values[column] = value
    async with write_transaction() as db:
        await _require_model(db, model_id)
        if values:
            assignments = ",".join(f"{column}=:{column}" for column in values)
            await db.execute(
                text(f"UPDATE llm_provider_model SET {assignments} WHERE id=:id"),
                {**values, "id": model_id},
            )
        row = await _require_model(db, model_id)
    audit_event("PROVIDER_MODEL_UPDATE", "success", actor_id=actor_id, target_id=model_id)
    return _model(row)


async def delete_model(model_id: int, actor_id: int) -> None:
    async with write_transaction() as db:
        await _require_model(db, model_id)
        await db.execute(text("DELETE FROM llm_provider_model WHERE id=:id"), {"id": model_id})
    audit_event("PROVIDER_MODEL_DELETE", "success", actor_id=actor_id, target_id=model_id)


async def set_model_active(model_id: int, active: bool, actor_id: int) -> None:
    async with write_transaction() as db:
        await _require_model(db, model_id)
        await db.execute(
            text("UPDATE llm_provider_model SET is_active=:active WHERE id=:id"),
            {"active": active, "id": model_id},
        )
    audit_event("PROVIDER_MODEL_ACTIVE", "success", actor_id=actor_id, target_id=model_id)
