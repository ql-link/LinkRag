"""B3 external model candidates; publication alone changes the formal catalog."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
from sqlalchemy import bindparam, text
from sqlalchemy.exc import DBAPIError

from src.api.management_http import BusinessError
from src.application.admin_model_catalog import _model, _page, _protocol
from src.application.model_configs import normalize_capability
from src.database import get_db_context, write_transaction
from src.observability.audit import audit_event

_SOURCE = "MODELS_DEV"
_OVERRIDES = {"claude": "anthropic", "gemini": "google",
              "moonshot": "moonshotai", "aliyun": "alibaba-cn"}


def _capabilities(model_id: str, display: str, inputs: list[str], outputs: list[str]) -> list[str]:
    name = (model_id + " " + display).lower()
    if "rerank" in name:
        return ["RERANK"]
    if "embed" in name or "embedding" in outputs:
        return ["EMBEDDING"]
    if any(word in name for word in ("whisper", "asr", "transcribe", "transcription",
                                     "speech-to-text")):
        return ["ASR"]
    result = []
    if "text" in outputs and "text" in inputs:
        result.append("CHAT")
    if "text" in outputs and any(item in inputs for item in ("image", "video", "pdf")):
        result.append("VISION")
    return result


def _models_for_provider(root: dict, provider_type: str) -> list[dict]:
    key = _OVERRIDES.get(provider_type, provider_type)
    provider = root.get(key)
    models = provider.get("models") if isinstance(provider, dict) else None
    if not isinstance(models, dict):
        raise BusinessError(10029, f"models.dev 未收录该厂商：{provider_type}", 400)
    entries = []
    for external_id, raw in models.items():
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("id") or external_id)
        display = str(raw.get("name") or name)
        modalities = raw.get("modalities") or {}
        if not isinstance(modalities, dict):
            modalities = {}
        inputs = [item.lower() for item in modalities.get("input", []) if isinstance(item, str)]
        outputs = [item.lower() for item in modalities.get("output", []) if isinstance(item, str)]
        limits = raw.get("limit") or {}
        if not isinstance(limits, dict):
            limits = {}
        try:
            released = date.fromisoformat(raw["release_date"]) if raw.get("release_date") else None
        except (ValueError, TypeError):
            released = None
        for capability in _capabilities(name, display, inputs, outputs):
            entries.append({"external_model_id": external_id, "model_name": name,
                            "display_name": display, "capability": capability,
                            "input_modalities": inputs, "output_modalities": outputs,
                            "context_window": limits.get("context") if isinstance(limits.get("context"), int) else None,
                            "max_output_tokens": limits.get("output") if isinstance(limits.get("output"), int) else None,
                            "model_release_date": released, "raw_metadata": raw})
    return entries


def _facts(provider: dict, capability: str) -> tuple[str, str | None]:
    kind = provider["provider_type"]
    protocol = ("anthropic" if kind == "claude" else "google" if kind == "gemini"
                else "jina" if kind == "jina" else "dashscope"
                if kind == "aliyun" and capability in {"RERANK", "ASR"} else "openai")
    base = (provider["api_base_url"] or "").rstrip("/")
    if not base:
        return protocol, None
    if protocol == "anthropic":
        return protocol, base + ("/messages" if base.endswith("/v1") else "/v1/messages")
    if protocol == "google":
        return protocol, base
    if protocol == "jina":
        suffix = "/rerank" if capability == "RERANK" else "/embeddings"
    elif protocol == "dashscope":
        suffix = "/services/rerank/text-rerank/text-rerank" if capability == "RERANK" else ""
    else:
        suffix = ("/chat/completions" if capability in {"CHAT", "VISION"}
                  else "/embeddings" if capability in {"EMBEDDING", "SPARSE_EMBEDDING"}
                  else "/audio/transcriptions" if capability == "ASR" else "")
    return protocol, base if not suffix or base.endswith(suffix) else base + suffix


async def _fetch_catalog() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            response = await client.get("https://models.dev/api.json")
            response.raise_for_status()
            root = response.json()
        if not isinstance(root, dict):
            raise ValueError("invalid catalog")
        return root
    except (httpx.HTTPError, ValueError) as exc:
        raise BusinessError(50001, "读取 models.dev 模型目录失败", 500) from exc


def _job(row: dict) -> dict:
    names = {"provider_id": "providerId", "sync_source": "syncSource", "status": "status",
             "added_count": "addedCount", "updated_count": "updatedCount",
             "stale_count": "staleCount", "error_message": "errorMessage",
             "started_at": "startedAt", "finished_at": "finishedAt"}
    return {"id": int(row["id"]), **{alias: row[column] for column, alias in names.items()}}


def _candidate(row: dict) -> dict:
    names = {"job_id": "jobId", "provider_id": "providerId", "sync_source": "syncSource",
             "external_model_id": "externalModelId", "model_name": "modelName",
             "display_name": "displayName", "inferred_capability": "inferredCapability",
             "inferred_protocol": "inferredProtocol", "inferred_api_base_url": "inferredApiBaseUrl",
             "context_window": "contextWindow", "max_output_tokens": "maxOutputTokens",
             "model_release_date": "releaseDate", "input_modalities": "inputModalities",
             "output_modalities": "outputModalities", "raw_metadata": "rawMetadata",
             "review_status": "reviewStatus", "matched_provider_model_id": "matchedProviderModelId",
             "last_seen_at": "lastSeenAt", "created_at": "createdAt", "updated_at": "updatedAt"}
    return {"id": int(row["id"]), "capability": row["inferred_capability"],
            **{alias: row[column] for column, alias in names.items()}}


async def refresh(provider_id: int, source: str | None, actor_id: int) -> dict:
    normalized = (source or _SOURCE).strip().upper()
    if normalized != _SOURCE:
        raise BusinessError(10029, "模型同步来源不支持", 400)
    async with get_db_context() as db:
        provider = (await db.execute(text("SELECT * FROM llm_system_provider WHERE id=:id"),
                                     {"id": provider_id})).mappings().one_or_none()
    if provider is None:
        raise BusinessError(10001, "系统厂商不存在", 404)
    async with write_transaction() as db:
        result = await db.execute(text("""
            INSERT INTO llm_provider_model_sync_job(provider_id,sync_source,status)
            VALUES(:pid,:source,'RUNNING')
        """), {"pid": provider_id, "source": normalized})
        job_id = int(result.lastrowid)
    try:
        entries = _models_for_provider(await _fetch_catalog(), provider["provider_type"])
        async with write_transaction() as db:
            local = (await db.execute(text("SELECT id,model_name,capability FROM llm_provider_model "
                                           "WHERE provider_id=:pid"),
                                      {"pid": provider_id})).mappings().all()
            indexed = {(row["model_name"], row["capability"]): int(row["id"]) for row in local}
            seen: set[tuple[str, str]] = set()
            added = updated = 0
            for entry in entries:
                cap = entry["capability"]
                identity = (entry["model_name"], cap)
                if identity in seen:
                    continue
                seen.add(identity)
                matched = indexed.get(identity)
                if matched is None:
                    added += 1
                else:
                    updated += 1
                protocol, url = _facts(dict(provider), cap)
                await db.execute(text("""
                    INSERT INTO llm_provider_model_sync_candidate
                      (job_id,provider_id,sync_source,external_model_id,model_name,
                       display_name,inferred_capability,inferred_protocol,
                       inferred_api_base_url,context_window,max_output_tokens,
                       model_release_date,input_modalities,output_modalities,raw_metadata,
                       review_status,matched_provider_model_id,last_seen_at)
                    VALUES(:job_id,:provider_id,:sync_source,:external_model_id,:model_name,
                           :display_name,:capability,:protocol,:url,:context_window,
                           :max_output_tokens,:model_release_date,:input_modalities,
                           :output_modalities,:raw_metadata,'PENDING',:matched,NOW())
                    ON DUPLICATE KEY UPDATE job_id=VALUES(job_id),
                      external_model_id=VALUES(external_model_id),
                      display_name=VALUES(display_name),
                      inferred_protocol=VALUES(inferred_protocol),
                      inferred_api_base_url=VALUES(inferred_api_base_url),
                      context_window=VALUES(context_window),
                      max_output_tokens=VALUES(max_output_tokens),
                      model_release_date=VALUES(model_release_date),
                      input_modalities=VALUES(input_modalities),
                      output_modalities=VALUES(output_modalities),
                      raw_metadata=VALUES(raw_metadata),
                      matched_provider_model_id=VALUES(matched_provider_model_id),
                      last_seen_at=NOW()
                """), {"job_id": job_id, "provider_id": provider_id,
                        "sync_source": normalized, "external_model_id": entry["external_model_id"],
                        "model_name": entry["model_name"], "display_name": entry["display_name"],
                        "capability": cap, "protocol": protocol, "url": url,
                        "context_window": entry["context_window"],
                        "max_output_tokens": entry["max_output_tokens"],
                        "model_release_date": entry["model_release_date"],
                        "input_modalities": json.dumps(entry["input_modalities"]),
                        "output_modalities": json.dumps(entry["output_modalities"]),
                        "raw_metadata": json.dumps(entry["raw_metadata"], ensure_ascii=False),
                        "matched": matched})
            stale = sum(1 for identity in indexed if identity not in seen)
            await db.execute(text("""
                UPDATE llm_provider_model_sync_job
                SET status='SUCCESS',added_count=:added,updated_count=:updated,
                    stale_count=:stale,finished_at=NOW() WHERE id=:job_id
            """), {"added": added, "updated": updated, "stale": stale, "job_id": job_id})
            row = (await db.execute(text("SELECT * FROM llm_provider_model_sync_job WHERE id=:id"),
                                    {"id": job_id})).mappings().one()
    except Exception as exc:
        async with write_transaction() as db:
            await db.execute(text("""
                UPDATE llm_provider_model_sync_job
                SET status='FAILED',error_message=:reason,finished_at=NOW() WHERE id=:id
            """), {"id": job_id, "reason": str(exc)[:512] or type(exc).__name__})
        audit_event("MODEL_SYNC_REFRESH", "failed", actor_id=actor_id, target_id=provider_id)
        raise
    audit_event("MODEL_SYNC_REFRESH", "success", actor_id=actor_id, target_id=provider_id)
    return _job(dict(row))


async def _list(table: str, filters: dict, page: int, size: int, order: str, mapper) -> dict:
    clauses = []
    params: dict[str, Any] = {"size": size, "offset": (page - 1) * size}
    for column, value in filters.items():
        if value is not None and value != "":
            clauses.append(f"{column}=:{column}")
            params[column] = value
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    try:
        async with get_db_context() as db:
            total = int((await db.execute(text(f"SELECT COUNT(*) FROM {table}" + where),
                                          params)).scalar_one())
            rows = (await db.execute(text(f"SELECT * FROM {table}" + where +
                                          f" ORDER BY {order} LIMIT :size OFFSET :offset"),
                                     params)).mappings().all()
    except DBAPIError as exc:
        # Read routes are mounted before the additive 0040 migration is
        # applied; report that deployment precondition without leaking SQL.
        if getattr(exc.orig, "args", (None,))[0] == 1146:
            raise BusinessError(503, "模型同步数据表尚未迁移", 503) from exc
        raise
    return _page([mapper(dict(row)) for row in rows], total, page, size)


async def list_jobs(page: int, size: int, provider_id: int | None,
                    source: str | None, status: str | None) -> dict:
    return await _list("llm_provider_model_sync_job",
                       {"provider_id": provider_id,
                        "sync_source": source.strip().upper() if source else None,
                        "status": status.strip().upper() if status else None},
                       page, size, "started_at DESC,id DESC", _job)


async def list_candidates(page: int, size: int, provider_id: int | None,
                          job_id: int | None, review_status: str | None,
                          capability: str | None) -> dict:
    return await _list("llm_provider_model_sync_candidate",
                       {"provider_id": provider_id, "job_id": job_id,
                        "review_status": review_status.strip().upper() if review_status else None,
                        "inferred_capability": normalize_capability(capability) if capability else None},
                       page, size, "last_seen_at DESC,id DESC", _candidate)


async def review(candidate_id: int, status: str, actor_id: int) -> dict:
    normalized = status.upper()
    if normalized not in {"PENDING", "REJECTED"}:
        raise BusinessError(10011, "候选审核状态只支持 PENDING/REJECTED", 400)
    async with write_transaction() as db:
        row = (await db.execute(text("SELECT id FROM llm_provider_model_sync_candidate "
                                     "WHERE id=:id FOR UPDATE"),
                                {"id": candidate_id})).scalar_one_or_none()
        if row is None:
            raise BusinessError(10030, "模型同步候选不存在", 404)
        await db.execute(text("UPDATE llm_provider_model_sync_candidate "
                              "SET review_status=:status WHERE id=:id"),
                         {"status": normalized, "id": candidate_id})
        item = (await db.execute(text("SELECT * FROM llm_provider_model_sync_candidate "
                                      "WHERE id=:id"), {"id": candidate_id})).mappings().one()
    audit_event("MODEL_SYNC_REVIEW", "success", actor_id=actor_id, target_id=candidate_id)
    return _candidate(dict(item))


async def publish(candidate_ids: list[int], overrides: dict, actor_id: int) -> list[dict]:
    ids = list(dict.fromkeys(candidate_ids))
    if not ids:
        raise BusinessError(10011, "请至少选择一个待发布能力", 400)
    stmt = text("SELECT * FROM llm_provider_model_sync_candidate WHERE id IN :ids FOR UPDATE")
    stmt = stmt.bindparams(bindparam("ids", expanding=True))
    result: list[dict] = []
    async with write_transaction() as db:
        rows = (await db.execute(stmt, {"ids": ids})).mappings().all()
        by_id = {int(row["id"]): dict(row) for row in rows}
        if len(by_id) != len(ids):
            raise BusinessError(10030, "模型同步候选不存在", 404)
        items = [by_id[item] for item in ids]
        first = items[0]
        if len(items) > 1:
            identity = (first["provider_id"], first["sync_source"],
                        first["external_model_id"], first["model_name"])
            if any((item["provider_id"], item["sync_source"], item["external_model_id"],
                    item["model_name"]) != identity for item in items):
                raise BusinessError(10011, "只能批量发布同一外部模型的能力", 400)
            if len({item["inferred_capability"] for item in items}) != len(items):
                raise BusinessError(10011, "同一能力不能重复发布", 400)
        for item in items:
            name = overrides.get("modelName") or item["model_name"]
            display = (overrides.get("displayName") if "displayName" in overrides
                       else item["display_name"])
            capability = normalize_capability(
                (overrides.get("capability") if len(items) == 1 else None)
                or item["inferred_capability"]
            )
            protocol = _protocol((overrides.get("protocol") if len(items) == 1 else None)
                                 or item["inferred_protocol"])
            url = (overrides.get("apiBaseUrl") if len(items) == 1 else None) or item["inferred_api_base_url"]
            if not url or not url.strip():
                raise BusinessError(10014, "模型能力缺少协议或入口，无法保存或展开", 400)
            saved = await db.execute(text("""
                INSERT INTO llm_provider_model
                  (provider_id,model_name,display_name,capability,protocol,api_base_url,is_active)
                VALUES(:pid,:name,:display,:cap,:protocol,:url,1)
                ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id),
                  display_name=VALUES(display_name),protocol=VALUES(protocol),
                  api_base_url=VALUES(api_base_url),is_active=1
            """), {"pid": item["provider_id"], "name": name,
                    "display": display, "cap": capability, "protocol": protocol, "url": url})
            model_id = int(saved.lastrowid)
            await db.execute(text("UPDATE llm_provider_model_sync_candidate "
                                  "SET review_status='PUBLISHED',matched_provider_model_id=:model_id "
                                  "WHERE id=:id"),
                             {"model_id": model_id, "id": item["id"]})
            row = (await db.execute(text("SELECT * FROM llm_provider_model WHERE id=:id"),
                                    {"id": model_id})).mappings().one()
            result.append(_model(dict(row)))
    audit_event("MODEL_SYNC_PUBLISH", "success", actor_id=actor_id)
    return result
