"""B5 original-file queries over shared MySQL and existing object storage."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.management_http import BusinessError
from src.application.datasets import owned_dataset
from src.config import settings
from src.database import get_db_context
from src.services.storage.factory import StorageFactory

_BEIJING = ZoneInfo("Asia/Shanghai")


def _file_datetime(value, *, database_generated: bool = True):
    """无时区 DATETIME 按写入来源和切换边界解释；不改变数据库原值。"""
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        boundary = settings.FILE_DB_BEIJING_SINCE
        local = database_generated and boundary is not None and value >= boundary
        value = value.replace(tzinfo=_BEIJING if local else timezone.utc)
    return value.astimezone(_BEIJING)


def _file_time(value, *, database_generated: bool = True):
    value = _file_datetime(value, database_generated=database_generated)
    return value.isoformat() if isinstance(value, datetime) else value


def _activity_time(row: dict):
    # f/pf 是数据库默认时间；p 始终由解析 ORM 显式 UTC 写入。
    candidates = [
        _file_datetime(row.get("updated_at")),
        _file_datetime(row.get("parse_pointer_updated_at")),
        _file_datetime(row.get("pipeline_updated_at"), database_generated=False),
    ]
    times = [value for value in candidates if isinstance(value, datetime)]
    return max(times).isoformat() if times else _file_time(row.get("updated_at"))


def _dto(row: dict, summary: dict | None = None) -> dict:
    status = {"success": "UPLOAD_SUCCESS", "failed": "UPLOAD_FAILED"}.get(
        row["upload_status"], "UPLOADING"
    )
    return {
        "id": int(row["id"]),
        "datasetId": int(row["dataset_id"]),
        "originalFilename": row["original_filename"],
        "fileSuffix": row["file_suffix"],
        "fileSize": int(row["file_size"]),
        "uploadStatus": status,
        "isUploadSuccess": bool(row["is_upload_success"]),
        "failureReason": row["failure_reason"],
        "assetSummary": summary,
        "createdAt": _file_time(row["created_at"]),
        "updatedAt": _file_time(row["updated_at"]),
    }


async def owned_file(db: AsyncSession, user_id: int, file_id: int) -> dict:
    row = (
        (
            await db.execute(
                text("""
        SELECT f.* FROM document_original_file f
        JOIN dataset d ON d.id=f.dataset_id AND d.user_id=f.user_id AND d.is_deleted=0
        WHERE f.id=:fid AND f.user_id=:uid AND f.is_deleted=0
    """),
                {"fid": file_id, "uid": user_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise BusinessError(404, "文件不存在或无权访问", 404)
    return dict(row)


async def _asset_summary(row: dict, *, required: bool) -> dict | None:
    key = row.get("object_key") or ""
    if not (key.startswith("markdown-assets/v1/") and key.endswith("/source/normalized.md")):
        return None
    manifest_key = key.removesuffix("source/normalized.md") + "manifest.json"
    try:
        with TemporaryDirectory(prefix="tolink-markdown-manifest-") as directory:
            path = Path(directory) / "manifest.json"
            await asyncio.to_thread(
                StorageFactory.get_storage().download_to_path,
                settings.MINIO_RAW_BUCKET,
                manifest_key,
                path,
            )
            manifest = json.loads(path.read_text(encoding="utf-8"))
        if (
            manifest.get("version") != 1
            or manifest.get("fileId") != row["id"]
            or manifest.get("userId") != row["user_id"]
            or manifest.get("datasetId") != row["dataset_id"]
            or manifest.get("source", {}).get("normalizedObjectKey") != key
            or not isinstance(manifest.get("summary"), dict)
        ):
            raise ValueError("invalid manifest identity")
        return manifest["summary"]
    except Exception as exc:
        if required:
            raise BusinessError(50004, "Markdown 图片清单暂时不可用", 503) from exc
        return None


async def detail(user_id: int, file_id: int) -> dict:
    async with get_db_context() as db:
        row = await owned_file(db, user_id, file_id)
    return _dto(row, await _asset_summary(row, required=True))


async def list_files(
    user_id: int,
    dataset_id: int | None,
    page: int,
    page_size: int,
    upload_status: str | None = None,
) -> dict:
    params: dict = {"uid": user_id, "limit": page_size, "offset": (page - 1) * page_size}
    where = "f.user_id=:uid AND f.is_deleted=0 AND d.is_deleted=0"
    if dataset_id is not None:
        params["did"] = dataset_id
        where += " AND f.dataset_id=:did"
    if upload_status and upload_status.strip():
        params["status"] = upload_status.lower().replace("upload_", "")
        where += " AND f.upload_status=:status"
    base = " FROM document_original_file f JOIN dataset d ON d.id=f.dataset_id "
    base += "AND d.user_id=f.user_id WHERE " + where
    async with get_db_context() as db:
        if dataset_id is not None:
            await owned_dataset(db, user_id, dataset_id)
        total = (await db.execute(text("SELECT COUNT(*)" + base), params)).scalar_one()
        rows = (
            (
                await db.execute(
                    text(
                        "SELECT f.*" + base + " ORDER BY f.created_at DESC,f.id DESC "
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


# 等权阶段完成度反映已完成的工作节点，不表示页数或字节完成比例。
_PARSE_STAGES = (
    ("cleaning", "文档解析与清洗"),
    ("chunking", "分块"),
    ("vectorizing", "稠密向量化"),
    ("pretokenize", "预分词"),
    ("es_indexing", "全文索引"),
    ("sparse_vectorizing", "稀疏向量化"),
)


def _parse_progress(row: dict) -> dict:
    stages = [
        {"key": key, "label": label, "status": row.get(key + "_status") or "PENDING"}
        for key, label in _PARSE_STAGES
    ]
    completed = sum(stage["status"] == "SUCCESS" for stage in stages)
    status = row.get("pipeline_status")
    active = [stage["label"] for stage in stages if stage["status"] == "PROCESSING"]
    return {
        "taskId": row.get("latest_parse_task_id"),
        "updatedAt": _activity_time(row),
        "progress": 100 if status == "SUCCESS" else min(99, completed * 100 // len(stages)),
        "progressKind": "stages",
        "stageLabel": "、".join(active) or ("等待任务执行" if not completed else "等待后续阶段"),
        "stages": stages,
    }


async def parse_results(user_id: int, dataset_id: int, file_ids: list[int]) -> list[dict]:
    ids = list(dict.fromkeys(file_ids))
    if not ids:
        raise BusinessError(400, "请选择要查看的文件", 400)
    stmt = text("""
        SELECT f.*,pf.latest_parse_task_id,l.parsed_filename,
               p.pipeline_status,p.failure_reason AS parse_failure_reason,
               p.cleaning_status,p.chunking_status,p.vectorizing_status,
               p.pretokenize_status,p.es_indexing_status,p.sparse_vectorizing_status,
               pf.updated_at AS parse_pointer_updated_at,
               p.updated_at AS pipeline_updated_at
        FROM document_original_file f
        LEFT JOIN document_parse_file pf ON pf.document_original_file_id=f.id
        LEFT JOIN document_parsed_log l ON l.task_id=pf.latest_parse_task_id
        LEFT JOIN document_parse_pipeline p ON p.task_id=pf.latest_parse_task_id
        WHERE f.id IN :ids AND f.user_id=:uid AND f.dataset_id=:did AND f.is_deleted=0
    """).bindparams(bindparam("ids", expanding=True))
    async with get_db_context() as db:
        await owned_dataset(db, user_id, dataset_id)
        rows = (
            (await db.execute(stmt, {"ids": ids, "uid": user_id, "did": dataset_id}))
            .mappings()
            .all()
        )
    by_id = {int(row["id"]): dict(row) for row in rows}
    if len(by_id) != len(ids):
        raise BusinessError(404, "文件不存在或无权访问", 404)
    result = []
    for file_id in ids:
        row = by_id[file_id]
        status = row["pipeline_status"]
        if status == "SUCCESS":
            parsed, frontend = "success", "parse_success"
        elif status == "FAILED":
            parsed, frontend = "failed", "parse_failed"
        elif row["latest_parse_task_id"]:
            parsed, frontend = "created", "parsing"
        else:
            parsed, frontend = None, "parse_waiting"
        filename = row["original_filename"]
        parsed_name = row["parsed_filename"] or filename.rsplit(".", 1)[0] + ".md"
        result.append(
            {
                "fileId": file_id,
                "originalFilename": filename,
                "parsedFilename": parsed_name,
                "frontendStatus": frontend,
                "parseStatus": parsed,
                "failureReason": row["parse_failure_reason"] if status == "FAILED" else None,
                "assetSummary": await _asset_summary(row, required=False),
                **_parse_progress(row),
            }
        )
    return result
