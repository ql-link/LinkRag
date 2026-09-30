"""B3 control-plane operations backed by the existing LLM tables and cache."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.management_http import BusinessError
from src.cache.llm_runtime_cache import LLMRuntimeCache
from src.core.llm.encryption import decrypt_api_key, encrypt_api_key, mask_api_key
from src.application.object_uploads import public_object_url
from src.database import get_db_context, write_transaction
from src.observability.audit import audit_event

CAPABILITIES = ("CHAT", "EMBEDDING", "SPARSE_EMBEDDING", "VISION", "RERANK", "ASR")


def normalize_capability(value: str | None) -> str:
    result = (value or "").upper()
    if result not in CAPABILITIES:
        raise BusinessError(10011, "模型能力标识无效", 400)
    return result


def _dto(row: dict, actor_id: int) -> dict:
    encrypted = row["api_key"]
    try:
        masked = mask_api_key(decrypt_api_key(encrypted)) if encrypted else "****"
    except Exception as exc:
        # A wrong deployment key must fail closed without exposing ciphertext.
        audit_event("LLM_CONFIG_DECRYPT", "failed", target_id=int(row["id"]))
        raise BusinessError(503, "模型配置密钥不可用", 503) from exc
    return {
        "configId": int(row["id"]),
        "scope": row["scope"],
        "providerId": int(row["provider_id"]),
        "providerType": row["provider_type"],
        "providerName": row["provider_name"],
        "iconUrl": public_object_url(row.get("icon_object_key"), row["icon_url"]),
        "modelName": row["model_name"],
        "displayName": row["display_name"] or row["model_name"],
        "capability": row["capability"],
        "protocol": row["protocol"],
        "apiBaseUrl": row["api_base_url"],
        "apiKeyMasked": masked,
        "isActive": bool(row["is_active"]),
        "editable": row["scope"] == "USER" and int(row["owner_user_id"]) == actor_id,
        "snapshotVersion": int(row["snapshot_version"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


_CONFIG_SELECT = """
SELECT c.*, p.provider_name, p.icon_url, p.icon_object_key
FROM llm_model_config c
LEFT JOIN llm_system_provider p ON p.id=c.provider_id
"""


async def list_visible_configs(
    user_id: int,
    *,
    provider_type: str | None = None,
    capability: str | None = None,
    is_active: bool | None = None,
    system_only: bool = False,
) -> list[dict]:
    clauses = ["(c.scope='SYSTEM' AND c.owner_user_id=0)"]
    params: dict = {}
    if not system_only:
        clauses.append("(c.scope='USER' AND c.owner_user_id=:uid)")
        params["uid"] = user_id
    where = "(" + " OR ".join(clauses) + ")"
    if provider_type is not None:
        where += " AND c.provider_type=:provider_type"
        params["provider_type"] = provider_type
    if capability and capability.strip():
        where += " AND c.capability=:capability"
        params["capability"] = normalize_capability(capability)
    if is_active is not None:
        where += " AND c.is_active=:active"
        params["active"] = is_active
    async with get_db_context() as db:
        rows = (
            (
                await db.execute(
                    text(
                        _CONFIG_SELECT
                        + " WHERE "
                        + where
                        + " ORDER BY c.capability,c.scope,c.model_name"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
    result = [_dto(dict(row), 0 if system_only else user_id) for row in rows]
    if system_only:
        for item in result:
            item["editable"] = True
    return result


async def list_provider_catalog(capability: str | None) -> list[dict]:
    params: dict = {}
    filter_clause = ""
    if capability and capability.strip():
        params["capability"] = normalize_capability(capability)
        filter_clause = " AND m.capability=:capability"
    async with get_db_context() as db:
        rows = (
            (
                await db.execute(
                    text("""
            SELECT p.id,p.provider_type,p.provider_name,p.icon_url,p.icon_object_key,
                   m.model_name,m.display_name,m.capability,m.protocol,m.api_base_url
            FROM llm_system_provider p
            JOIN llm_provider_model m ON m.provider_id=p.id AND m.is_active=1
            WHERE p.is_active=1 AND p.provider_type<>'linkrag'
        """ + filter_clause + " ORDER BY p.priority DESC,p.id,m.id"),
                    params,
                )
            )
            .mappings()
            .all()
        )
    providers: OrderedDict[int, dict] = OrderedDict()
    models: dict[tuple[int, str], dict] = {}
    for row in rows:
        provider_id = int(row["id"])
        provider = providers.setdefault(
            provider_id,
            {
                "providerType": row["provider_type"],
                "providerName": row["provider_name"],
                "iconUrl": public_object_url(row.get("icon_object_key"), row["icon_url"]),
                "models": [],
            },
        )
        key = (provider_id, row["model_name"])
        model = models.get(key)
        if model is None:
            model = {
                "modelName": row["model_name"],
                "displayName": row["display_name"] or row["model_name"],
                "capabilities": [],
            }
            models[key] = model
            provider["models"].append(model)
        model["capabilities"].append(
            {
                "capability": row["capability"],
                "protocol": row["protocol"],
                "apiBaseUrl": row["api_base_url"],
            }
        )
    return list(providers.values())


async def _config_row(db: AsyncSession, config_id: int) -> dict | None:
    row = (
        (
            await db.execute(
                text(
                    "SELECT id,scope,owner_user_id,is_active,capability "
                    "FROM llm_model_config WHERE id=:id"
                ),
                {"id": config_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


async def require_executable(
    db: AsyncSession, user_id: int, config_id: int, capability: str
) -> dict:
    """The Java/Python error order is missing, inactive, forbidden, capability."""
    row = await _config_row(db, config_id)
    if row is None:
        raise BusinessError(10020, "LLM配置不存在", 404)
    if not row["is_active"]:
        raise BusinessError(10021, "LLM配置已停用", 409)
    if row["scope"] not in {"USER", "SYSTEM"} or (
        row["scope"] == "USER" and int(row["owner_user_id"]) != user_id
    ):
        raise BusinessError(10022, "无权使用该LLM配置", 403)
    if row["capability"] != normalize_capability(capability):
        raise BusinessError(10023, "LLM配置能力不匹配", 400)
    return row


async def _default(db: AsyncSession, user_id: int, capability: str) -> dict:
    row = (
        await db.execute(
            text(
                "SELECT config_id FROM llm_capability_default "
                "WHERE scope='USER' AND owner_user_id=:uid AND capability=:cap"
            ),
            {"uid": user_id, "cap": capability},
        )
    ).scalar_one_or_none()
    if row is not None:
        await require_executable(db, user_id, int(row), capability)
    return {"capability": capability, "configId": int(row) if row is not None else None}


async def get_default(user_id: int, capability: str) -> dict:
    cap = normalize_capability(capability)
    async with get_db_context() as db:
        return await _default(db, user_id, cap)


async def list_defaults(user_id: int) -> list[dict]:
    async with get_db_context() as db:
        return [await _default(db, user_id, cap) for cap in CAPABILITIES]


async def set_default(user_id: int, capability: str, config_id: int) -> dict:
    cap = normalize_capability(capability)
    async with write_transaction() as db:
        await require_executable(db, user_id, config_id, cap)
        await db.execute(
            text("""
            INSERT INTO llm_capability_default(scope,owner_user_id,capability,config_id)
            VALUES('USER',:uid,:cap,:cid)
            ON DUPLICATE KEY UPDATE config_id=VALUES(config_id)
        """),
            {"uid": user_id, "cap": cap, "cid": config_id},
        )
    return {"capability": cap, "configId": config_id}


async def clear_default(user_id: int, capability: str) -> dict:
    cap = normalize_capability(capability)
    async with write_transaction() as db:
        await db.execute(
            text(
                "DELETE FROM llm_capability_default WHERE scope='USER' "
                "AND owner_user_id=:uid AND capability=:cap"
            ),
            {"uid": user_id, "cap": cap},
        )
    return {"capability": cap, "configId": None}


async def invalidate_runtime(config_ids: list[int]) -> None:
    cache = LLMRuntimeCache()
    for config_id in set(config_ids):
        try:
            await cache.invalidate(config_id)
        except Exception as exc:
            audit_event("LLM_RUNTIME_CACHE_EVICT", "failed", target_id=config_id)
            raise BusinessError(503, "配置已保存，但缓存失效失败", 503) from exc


async def setup_provider(user_id: int, provider_type: str, api_key: str) -> list[dict]:
    if provider_type.lower() == "linkrag":
        raise BusinessError(10016, "系统服务厂商不支持用户自配", 400)
    encrypted = encrypt_api_key(api_key)
    touched: list[int] = []
    async with write_transaction() as db:
        provider = (
            (
                await db.execute(
                    text(
                        "SELECT id,is_active FROM llm_system_provider " "WHERE provider_type=:type"
                    ),
                    {"type": provider_type},
                )
            )
            .mappings()
            .one_or_none()
        )
        if provider is None:
            raise BusinessError(10001, "系统厂商不存在", 404)
        if not provider["is_active"]:
            raise BusinessError(10002, "系统厂商已被禁用", 400)
        models = (
            (
                await db.execute(
                    text(
                        "SELECT model_name,display_name,capability,protocol,api_base_url "
                        "FROM llm_provider_model WHERE provider_id=:pid AND is_active=1"
                    ),
                    {"pid": provider["id"]},
                )
            )
            .mappings()
            .all()
        )
        if not models:
            raise BusinessError(10019, "启用厂商前至少需要上架一个模型", 400)
        for model in models:
            if not all(
                model[k] and str(model[k]).strip()
                for k in ("model_name", "capability", "protocol", "api_base_url")
            ):
                raise BusinessError(10014, "模型能力缺少协议或入口，无法保存或展开", 400)
            normalize_capability(model["capability"])
        for model in models:
            result = await db.execute(
                text("""
                INSERT INTO llm_model_config
                  (scope,owner_user_id,provider_id,provider_type,model_name,display_name,
                   capability,protocol,api_base_url,api_key,is_active,snapshot_version)
                VALUES ('USER',:uid,:pid,:ptype,:model,:display,:cap,:protocol,:url,:key,1,1)
                ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id),
                  provider_type=VALUES(provider_type),display_name=VALUES(display_name),
                  protocol=VALUES(protocol),api_base_url=VALUES(api_base_url),
                  api_key=VALUES(api_key),snapshot_version=snapshot_version+1
            """),
                {
                    "uid": user_id,
                    "pid": provider["id"],
                    "ptype": provider_type,
                    "model": model["model_name"],
                    "display": model["display_name"],
                    "cap": model["capability"],
                    "protocol": model["protocol"],
                    "url": model["api_base_url"],
                    "key": encrypted,
                },
            )
            touched.append(int(cast(CursorResult[Any], result).lastrowid))
    await invalidate_runtime(touched)
    visible = await list_visible_configs(user_id)
    touched_set = set(touched)
    audit_event("LLM_PROVIDER_SETUP", "success", actor_id=user_id)
    return [item for item in visible if item["configId"] in touched_set]


async def _owned_config(db: AsyncSession, user_id: int, config_id: int, *, admin: bool) -> dict:
    row = await _config_row(db, config_id)
    if row is None:
        raise BusinessError(10020, "LLM配置不存在", 404)
    if admin:
        allowed = row["scope"] == "SYSTEM"
    else:
        allowed = row["scope"] == "USER" and int(row["owner_user_id"]) == user_id
    if not allowed:
        raise BusinessError(10022, "无权使用该LLM配置", 403)
    return row


async def _ensure_unused(db: AsyncSession, config_id: int) -> None:
    count = (
        await db.execute(
            text("""
        SELECT COUNT(*) FROM dataset_parse_config
        WHERE sparse_embedding_config_id=:cid OR dense_embedding_config_id=:cid
           OR enhancement_chat_config_id=:cid OR enhancement_vision_config_id=:cid
           OR rerank_config_id=:cid
    """),
            {"cid": config_id},
        )
    ).scalar_one()
    if count:
        raise BusinessError(10026, "LLM配置仍被数据集引用", 409)


async def change_active(
    user_id: int,
    config_id: int,
    is_active: bool,
    *,
    admin: bool = False,
    emergency: bool = False,
    confirmed: bool = False,
) -> None:
    changed = False
    async with write_transaction() as db:
        row = await _owned_config(db, user_id, config_id, admin=admin)
        if bool(row["is_active"]) == is_active:
            return
        if not is_active:
            if emergency:
                if not admin and not confirmed:
                    raise BusinessError(400, "紧急停用用户配置需要所有者明确确认", 400)
            else:
                await _ensure_unused(db, config_id)
            await db.execute(
                text("DELETE FROM llm_capability_default " "WHERE scope='USER' AND config_id=:cid"),
                {"cid": config_id},
            )
        await db.execute(
            text(
                "UPDATE llm_model_config SET is_active=:active, "
                "snapshot_version=snapshot_version+1 WHERE id=:cid"
            ),
            {"active": is_active, "cid": config_id},
        )
        changed = True
    if changed:
        await invalidate_runtime([config_id])
        audit_event("LLM_CONFIG_ACTIVE", "success", actor_id=user_id, target_id=config_id)


async def delete_config(user_id: int, config_id: int, *, admin: bool = False) -> None:
    async with write_transaction() as db:
        await _owned_config(db, user_id, config_id, admin=admin)
        await _ensure_unused(db, config_id)
        await db.execute(
            text("DELETE FROM llm_capability_default " "WHERE scope='USER' AND config_id=:cid"),
            {"cid": config_id},
        )
        await db.execute(text("DELETE FROM llm_model_config WHERE id=:cid"), {"cid": config_id})
    await invalidate_runtime([config_id])
    audit_event("LLM_CONFIG_DELETE", "success", actor_id=user_id, target_id=config_id)


_PROTOCOLS = frozenset(
    {"openai", "anthropic", "google", "jina", "dashscope", "bge_m3", "doubao_vision"}
)


async def _catalog_facts(
    db: AsyncSession, source_model_id: int | None, mutation: dict | None
) -> dict | None:
    if source_model_id is not None and mutation is not None:
        raise BusinessError(400, "sourceProviderModelId 与 catalogMutation 只能提供一个", 400)
    if source_model_id is not None:
        row = (
            (
                await db.execute(
                    text("SELECT * FROM llm_provider_model " "WHERE id=:id AND is_active=1"),
                    {"id": source_model_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise BusinessError(10008, "模型不被该厂商支持", 400)
        return dict(row)
    if mutation is None:
        return None
    provider_id = mutation.get("providerId")
    if provider_id is None:
        raise BusinessError(400, "catalogMutation.providerId不能为空", 400)
    provider = (
        await db.execute(
            text("SELECT id FROM llm_system_provider WHERE id=:id"), {"id": provider_id}
        )
    ).scalar_one_or_none()
    if provider is None:
        raise BusinessError(10001, "系统厂商不存在", 404)
    name = mutation.get("modelName")
    protocol = mutation.get("protocol")
    url = mutation.get("apiBaseUrl")
    capability = normalize_capability(mutation.get("capability"))
    if not name or not str(name).strip() or not url or not str(url).strip():
        raise BusinessError(10014, "模型能力缺少协议或入口，无法保存或展开", 400)
    if protocol not in _PROTOCOLS:
        raise BusinessError(10015, "协议不在支持范围内", 400)
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
            "name": name,
            "display": mutation.get("displayName") or None,
            "cap": capability,
            "protocol": protocol,
            "url": url,
        },
    )
    return {
        "id": int(cast(CursorResult[Any], result).lastrowid),
        "provider_id": provider_id,
        "model_name": name,
        "display_name": mutation.get("displayName"),
        "capability": capability,
        "protocol": protocol,
        "api_base_url": url,
    }


async def save_system_config(actor_id: int, body: dict, *, config_id: int | None = None) -> dict:
    touched: int
    async with write_transaction() as db:
        existing = await _owned_config(db, actor_id, config_id, admin=True) if config_id else None
        facts = await _catalog_facts(
            db, body.get("sourceProviderModelId"), body.get("catalogMutation")
        )
        if facts is None and existing is None:
            raise BusinessError(400, "创建平台配置必须提供模型目录事实", 400)
        linkrag = (
            await db.execute(
                text("SELECT id FROM llm_system_provider " "WHERE provider_type='linkrag'")
            )
        ).scalar_one_or_none()
        if linkrag is None:
            raise BusinessError(10001, "系统厂商不存在", 404)
        if facts is None:
            facts = dict(
                (
                    await db.execute(
                        text(
                            "SELECT model_name,display_name,capability,protocol,api_base_url "
                            "FROM llm_model_config WHERE id=:id"
                        ),
                        {"id": config_id},
                    )
                )
                .mappings()
                .one()
            )
        assert facts is not None
        if not all(
            facts.get(key) and str(facts[key]).strip()
            for key in ("model_name", "capability", "protocol", "api_base_url")
        ):
            raise BusinessError(10014, "模型能力缺少协议或入口，无法保存或展开", 400)
        capability = normalize_capability(facts["capability"])
        if existing and existing["capability"] != capability:
            raise BusinessError(10023, "已有配置不能原地修改能力，请创建新的平台配置", 400)
        key = body.get("apiKey")
        if existing:
            assignments = "api_key=:key," if key and key.strip() else ""
            await db.execute(
                text(
                    "UPDATE llm_model_config SET provider_id=:pid,provider_type='linkrag', "
                    "model_name=:name,display_name=:display,capability=:cap, "
                    "protocol=:protocol,api_base_url=:url,"
                    + assignments
                    + "snapshot_version=snapshot_version+1 WHERE id=:id"
                ),
                {
                    "pid": linkrag,
                    "name": facts["model_name"],
                    "display": facts["display_name"],
                    "cap": capability,
                    "protocol": facts["protocol"],
                    "url": facts["api_base_url"],
                    "key": encrypt_api_key(key) if key and key.strip() else None,
                    "id": config_id,
                },
            )
            assert config_id is not None
            touched = int(config_id)
        else:
            natural = (
                await db.execute(
                    text("""
                SELECT id FROM llm_model_config WHERE scope='SYSTEM' AND owner_user_id=0
                  AND provider_id=:pid AND model_name=:name AND capability=:cap
            """),
                    {"pid": linkrag, "name": facts["model_name"], "cap": capability},
                )
            ).scalar_one_or_none()
            if natural is None and not key:
                raise BusinessError(10007, "创建平台配置时API Key不能为空", 400)
            if natural is not None:
                existing_key = (
                    await db.execute(
                        text("SELECT api_key FROM llm_model_config " "WHERE id=:id"),
                        {"id": natural},
                    )
                ).scalar_one()
                encrypted = encrypt_api_key(key) if key and key.strip() else existing_key
            else:
                assert isinstance(key, str)
                encrypted = encrypt_api_key(key)
            result = await db.execute(
                text("""
                INSERT INTO llm_model_config
                  (scope,owner_user_id,provider_id,provider_type,model_name,display_name,
                   capability,protocol,api_base_url,api_key,is_active,snapshot_version)
                VALUES('SYSTEM',0,:pid,'linkrag',:name,:display,:cap,:protocol,:url,:key,1,1)
                ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id),
                  display_name=VALUES(display_name),protocol=VALUES(protocol),
                  api_base_url=VALUES(api_base_url),api_key=VALUES(api_key),
                  snapshot_version=snapshot_version+1
            """),
                {
                    "pid": linkrag,
                    "name": facts["model_name"],
                    "display": facts["display_name"],
                    "cap": capability,
                    "protocol": facts["protocol"],
                    "url": facts["api_base_url"],
                    "key": encrypted,
                },
            )
            touched = int(cast(CursorResult[Any], result).lastrowid)
    await invalidate_runtime([touched])
    configs = await list_visible_configs(0, system_only=True)
    return {"config": next(item for item in configs if item["configId"] == touched)}
