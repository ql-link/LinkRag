"""B4 dataset control plane; runtime config reads remain in core.dataset_config."""

from __future__ import annotations

import json
import math
from typing import Any, cast

from pydantic import BaseModel, ValidationError
from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.management_http import BusinessError
from src.application.model_configs import require_executable
from src.cache.dataset_parse_config_cache import DatasetParseConfigCache
from src.core.dataset_config.models import (
    ChunkingConfig,
    EnhancementConfig,
    PDFConfig,
    RecallConfig,
)
from src.database import get_db_context, write_transaction
from src.observability.audit import audit_event


def _dto(row: dict) -> dict:
    return {key: row[key] for key in ("id", "name", "description", "status")} | {
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


async def owned_dataset(db: AsyncSession, user_id: int, dataset_id: int) -> dict:
    row = (
        (
            await db.execute(
                text("SELECT * FROM dataset WHERE id=:id AND user_id=:uid " "AND is_deleted=0"),
                {"id": dataset_id, "uid": user_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise BusinessError(404, "数据集不存在或无权访问", 404)
    return dict(row)


async def detail(user_id: int, dataset_id: int) -> dict:
    async with get_db_context() as db:
        return _dto(await owned_dataset(db, user_id, dataset_id))


async def list_datasets(user_id: int, page: int, page_size: int) -> dict:
    async with get_db_context() as db:
        params = {"uid": user_id, "offset": (page - 1) * page_size, "limit": page_size}
        total = (
            await db.execute(
                text("SELECT COUNT(*) FROM dataset WHERE user_id=:uid " "AND is_deleted=0"), params
            )
        ).scalar_one()
        rows = (
            (
                await db.execute(
                    text(
                        "SELECT * FROM dataset WHERE user_id=:uid "
                        "AND is_deleted=0 ORDER BY updated_at DESC,id DESC "
                        "LIMIT :limit OFFSET :offset"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
    return {
        "items": [_dto(dict(row)) for row in rows],
        "total": int(total),
        "page": page,
        "pageSize": page_size,
        "totalPages": (int(total) + page_size - 1) // page_size,
    }


async def _binding(
    db: AsyncSession, user_id: int, config_id: int | None, capability: str, field: str
) -> None:
    if config_id is None:
        raise BusinessError(10028, "数据集模型绑定不合法", 400, data={"field": field})
    try:
        await require_executable(db, user_id, config_id, capability)
    except BusinessError as exc:
        raise BusinessError(10028, "数据集模型绑定不合法", 400, data={"field": field}) from exc


async def _evict(dataset_id: int) -> None:
    try:
        await DatasetParseConfigCache().invalidate(dataset_id)
    except Exception as exc:
        audit_event("DATASET_PARSE_CONFIG_CACHE_EVICT", "failed", target_id=dataset_id)
        raise BusinessError(503, "数据集配置已保存，但缓存失效失败", 503) from exc


async def create_dataset(
    user_id: int,
    name: str,
    description: str | None,
    dense_id: int,
    sparse_id: int,
) -> dict:
    normalized = name.strip()
    if not normalized:
        raise BusinessError(400, "数据集名称不能为空", 400)
    try:
        async with write_transaction() as db:
            await _binding(db, user_id, dense_id, "EMBEDDING", "dense_embedding_config_id")
            await _binding(db, user_id, sparse_id, "SPARSE_EMBEDDING", "sparse_embedding_config_id")
            result = await db.execute(
                text(
                    "INSERT INTO dataset(user_id,name,description,status,is_deleted,deleted_seq) "
                    "VALUES(:uid,:name,:description,'ACTIVE',0,0)"
                ),
                {"uid": user_id, "name": normalized, "description": description},
            )
            dataset_id = int(cast(CursorResult[Any], result).lastrowid)
            await db.execute(
                text("""
                INSERT INTO dataset_parse_config
                (user_id,dataset_id,chunking_config,enhancement_config,pdf_config,recall_config,
                 sparse_embedding_config_id,dense_embedding_config_id,is_active)
                VALUES(:uid,:did,:chunking,:enhancement,:pdf,:recall,:sparse,:dense,1)
            """),
                {
                    "uid": user_id,
                    "did": dataset_id,
                    "chunking": "{}",
                    "enhancement": json.dumps(
                        {
                            "enable_table_enhancement": False,
                            "enable_image_enhancement": False,
                            "enable_heading_hierarchy": False,
                        }
                    ),
                    "pdf": "{}",
                    "recall": json.dumps(
                        {
                            "enable_rerank": False,
                            "recall_enabled_sources": ["bm25", "sparse", "dense"],
                            "rerank_top_n": 8,
                            "recall_strict": False,
                        }
                    ),
                    "sparse": sparse_id,
                    "dense": dense_id,
                },
            )
    except IntegrityError as exc:
        raise BusinessError(400, "当前用户下已存在同名数据集", 400) from exc
    await _evict(dataset_id)
    audit_event("DATASET_CREATE", "success", actor_id=user_id, target_id=dataset_id)
    return await detail(user_id, dataset_id)


async def update_dataset(user_id: int, dataset_id: int, changes: dict[str, Any]) -> dict:
    values: dict[str, Any] = {}
    if changes.get("name") is not None:
        values["name"] = changes["name"].strip()
        if not values["name"]:
            raise BusinessError(400, "数据集名称不能为空", 400)
    if changes.get("description") is not None:
        values["description"] = changes["description"].strip()
    if not values:
        raise BusinessError(400, "请至少提供一个需要更新的字段", 400)
    try:
        async with write_transaction() as db:
            await owned_dataset(db, user_id, dataset_id)
            assignments = ",".join(f"{key}=:{key}" for key in values)
            await db.execute(
                text(f"UPDATE dataset SET {assignments} WHERE id=:id AND user_id=:uid"),
                {**values, "id": dataset_id, "uid": user_id},
            )
    except IntegrityError as exc:
        raise BusinessError(400, "当前用户下已存在同名数据集", 400) from exc
    return await detail(user_id, dataset_id)


def _json_value(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _config_response(row: dict | None) -> dict:
    ids = (
        "sparse_embedding_config_id",
        "dense_embedding_config_id",
        "enhancement_chat_config_id",
        "enhancement_vision_config_id",
        "rerank_config_id",
    )
    result = {key: row[key] if row else None for key in ids}
    for field, column in (
        ("chunking", "chunking_config"),
        ("enhancement", "enhancement_config"),
        ("pdf", "pdf_config"),
        ("recall", "recall_config"),
    ):
        result[field] = _json_value(row[column]) if row else {}
    recall = result["recall"]
    if not isinstance(recall, dict):
        recall = {}
        result["recall"] = recall
    recall.setdefault("enable_rerank", False)
    recall.setdefault("recall_enabled_sources", ["bm25", "sparse", "dense"])
    recall.setdefault("rerank_top_n", 8)
    recall.setdefault("recall_strict", False)
    return result


async def get_parse_config(user_id: int, dataset_id: int) -> dict:
    async with get_db_context() as db:
        await owned_dataset(db, user_id, dataset_id)
        row = (
            (
                await db.execute(
                    text(
                        "SELECT * FROM dataset_parse_config "
                        "WHERE user_id=:uid AND dataset_id=:did"
                    ),
                    {"uid": user_id, "did": dataset_id},
                )
            )
            .mappings()
            .one_or_none()
        )
    return _config_response(dict(row) if row else None)


def _normalized_configs(body: dict) -> dict[str, dict]:
    fields: dict[str, type[BaseModel]] = {
        "chunking": ChunkingConfig,
        "enhancement": EnhancementConfig,
        "pdf": PDFConfig,
        "recall": RecallConfig,
    }
    result: dict[str, dict] = {}
    for name, model in fields.items():
        raw = body.get(name) or {}
        if (
            name == "recall"
            and isinstance(raw, dict)
            and isinstance(raw.get("recall_enabled_sources"), list)
        ):
            raw = {
                **raw,
                "recall_enabled_sources": [
                    item
                    for item in raw["recall_enabled_sources"]
                    if isinstance(item, str) and item.strip()
                ],
            }
        try:
            value = model.model_validate(raw).model_dump(exclude_unset=True)
        except (ValidationError, ValueError, TypeError) as exc:
            raise BusinessError(400, f"{name} 配置不合法", 400) from exc
        if name == "pdf" and value.get("pdf_parser_backend") not in (
            None,
            "auto",
            "mineru",
            "opendataloader",
            "naive",
        ):
            raise BusinessError(
                400, "pdf_parser_backend 仅支持 auto/mineru/opendataloader/naive", 400
            )
        result[name] = {key: item for key, item in value.items() if item is not None}
    sources = result["recall"].get("recall_enabled_sources")
    for field in ("sparse_score_threshold", "dense_score_threshold"):
        threshold = result["recall"].get(field)
        if threshold is not None and (not math.isfinite(threshold) or threshold < 0):
            raise BusinessError(400, f"{field} 必须是不小于 0 的有限数", 400)
    if sources is not None:
        deduped = []
        for source in sources:
            if source is None or not str(source).strip():
                continue
            normalized = source.strip().lower()
            if normalized not in {"bm25", "sparse", "dense"}:
                raise BusinessError(400, "recall_enabled_sources 仅支持 bm25/sparse/dense", 400)
            if normalized not in deduped:
                deduped.append(normalized)
        result["recall"]["recall_enabled_sources"] = deduped
    return result


async def update_parse_config(user_id: int, dataset_id: int, body: dict) -> dict:
    config = _normalized_configs(body)
    binding_fields = {
        "dense_embedding_config_id": "EMBEDDING",
        "sparse_embedding_config_id": "SPARSE_EMBEDDING",
        "enhancement_chat_config_id": "CHAT",
        "enhancement_vision_config_id": "VISION",
        "rerank_config_id": "RERANK",
    }
    ids = {field: body.get(field) for field in binding_fields}
    required = {"dense_embedding_config_id", "sparse_embedding_config_id"}
    enhancement = config["enhancement"]
    if enhancement.get("enable_table_enhancement") or enhancement.get("enable_heading_hierarchy"):
        required.add("enhancement_chat_config_id")
    if enhancement.get("enable_image_enhancement"):
        required.add("enhancement_vision_config_id")
    if config["recall"].get("enable_rerank"):
        required.add("rerank_config_id")
    async with write_transaction() as db:
        await owned_dataset(db, user_id, dataset_id)
        existing = (
            (
                await db.execute(
                    text(
                        "SELECT dense_embedding_config_id,sparse_embedding_config_id "
                        "FROM dataset_parse_config WHERE user_id=:uid AND dataset_id=:did "
                        "FOR UPDATE"
                    ),
                    {"uid": user_id, "did": dataset_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        for field in ("dense_embedding_config_id", "sparse_embedding_config_id"):
            if existing and existing[field] is not None and existing[field] != ids[field]:
                raise BusinessError(10028, "数据集模型绑定不合法", 400, data={"field": field})
        for field, capability in binding_fields.items():
            if field in required or ids[field] is not None:
                await _binding(db, user_id, ids[field], capability, field)
        params = {"uid": user_id, "did": dataset_id, **ids}
        for name in ("chunking", "enhancement", "pdf", "recall"):
            params[name] = json.dumps(config[name], ensure_ascii=False)
        await db.execute(
            text("""
            INSERT INTO dataset_parse_config
              (user_id,dataset_id,chunking_config,enhancement_config,pdf_config,recall_config,
               sparse_embedding_config_id,dense_embedding_config_id,
               enhancement_chat_config_id,enhancement_vision_config_id,rerank_config_id,is_active)
            VALUES(:uid,:did,:chunking,:enhancement,:pdf,:recall,:sparse_embedding_config_id,
                   :dense_embedding_config_id,:enhancement_chat_config_id,
                   :enhancement_vision_config_id,:rerank_config_id,1)
            ON DUPLICATE KEY UPDATE
              chunking_config=VALUES(chunking_config),
              enhancement_config=VALUES(enhancement_config),pdf_config=VALUES(pdf_config),
              recall_config=VALUES(recall_config),
              sparse_embedding_config_id=VALUES(sparse_embedding_config_id),
              dense_embedding_config_id=VALUES(dense_embedding_config_id),
              enhancement_chat_config_id=VALUES(enhancement_chat_config_id),
              enhancement_vision_config_id=VALUES(enhancement_vision_config_id),
              rerank_config_id=VALUES(rerank_config_id)
        """),
            params,
        )
    await _evict(dataset_id)
    return await get_parse_config(user_id, dataset_id)
