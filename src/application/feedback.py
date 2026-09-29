"""B10 anonymous feedback and administrator workflow on the shared table."""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.management_http import BusinessError
from src.application.object_uploads import upload_object
from src.config import settings
from src.models.db_models import UserFeedbackDB
from src.observability.audit import audit_event
from src.services.storage.factory import StorageFactory

_TYPES = {"BUG", "FEATURE", "EXPERIENCE", "OTHER"}
_STATUSES = {"PENDING", "PROCESSING", "RESOLVED", "CLOSED"}


def _now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)


def _bad(message: str) -> BusinessError:
    return BusinessError(40020, message, 400)


def _type(value: str | None) -> str:
    normalized = (value or "").strip().upper() or "OTHER"
    if normalized not in _TYPES:
        raise _bad("不支持的反馈类型")
    return normalized


def _status(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    if normalized not in _STATUSES:
        raise _bad("不支持的反馈状态")
    return normalized


def _dto(row: UserFeedbackDB) -> dict:
    key = row.attachment_object_key
    url = (
        StorageFactory.get_storage().build_public_url(settings.MINIO_PUBLIC_BUCKET, key)
        if key
        else None
    )
    return {
        "id": row.id,
        "type": row.type,
        "title": row.title,
        "content": row.content,
        "attachmentObjectKey": key,
        "attachmentUrl": url,
        "status": row.status,
        "priority": row.priority,
        "adminId": row.admin_id,
        "adminReply": row.admin_reply,
        "processedAt": row.processed_at,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
    }


async def submit(
    db: AsyncSession,
    type_value: str | None,
    title: str,
    content: str,
    filename: str | None = None,
    attachment: bytes | None = None,
    mime: str | None = None,
) -> dict:
    if not title or not title.strip():
        raise _bad("反馈标题不能为空")
    if len(title.strip()) > 128:
        raise _bad("反馈标题不能超过 128 个字符")
    if not content or not content.strip():
        raise _bad("反馈内容不能为空")
    if len(content.strip()) > 5000:
        raise _bad("反馈内容不能超过 5000 个字符")
    feedback_type = _type(type_value)
    key = None
    storage = None
    if attachment is not None:
        if not attachment:
            raise _bad("反馈附件不能为空")
        storage = StorageFactory.get_storage()
        uploaded = await upload_object(
            "feedback", filename, attachment, mime, storage=storage
        )
        key = uploaded.key
    row = UserFeedbackDB(
        type=feedback_type,
        title=title.strip(),
        content=content.strip(),
        attachment_object_key=key,
        status="PENDING",
        priority=3,
        created_at=_now(),
        updated_at=_now(),
    )
    try:
        db.add(row)
        await db.commit()
    except Exception:
        await db.rollback()
        if key and storage:
            try:
                await asyncio.to_thread(
                    storage.remove_object, settings.MINIO_PUBLIC_BUCKET, key
                )
            except Exception:
                audit_event("FEEDBACK_ATTACHMENT_CLEANUP", "failed")
        raise
    await db.refresh(row)
    return _dto(row)


async def _get(db: AsyncSession, feedback_id: int) -> UserFeedbackDB:
    row = await db.get(UserFeedbackDB, feedback_id)
    if row is None:
        raise BusinessError(404, "反馈不存在", 404)
    return row


async def list_feedback(
    db: AsyncSession,
    page: int,
    page_size: int,
    status: str | None,
    type_value: str | None,
) -> dict:
    filters = []
    if status and status.strip():
        filters.append(UserFeedbackDB.status == _status(status))
    if type_value and type_value.strip():
        filters.append(UserFeedbackDB.type == _type(type_value))
    total = (
        await db.scalar(
            select(func.count()).select_from(UserFeedbackDB).where(*filters)
        )
        or 0
    )
    rows = (
        await db.scalars(
            select(UserFeedbackDB)
            .where(*filters)
            .order_by(UserFeedbackDB.created_at.desc(), UserFeedbackDB.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "items": [_dto(row) for row in rows],
        "total": int(total),
        "page": page,
        "pageSize": page_size,
        "totalPages": (int(total) + page_size - 1) // page_size,
    }


async def detail(db: AsyncSession, feedback_id: int) -> dict:
    return _dto(await _get(db, feedback_id))


async def update_status(db: AsyncSession, feedback_id: int, value: str) -> dict:
    status = _status(value)
    row = await _get(db, feedback_id)
    row.status = status
    if status in {"RESOLVED", "CLOSED"}:
        row.processed_at = _now()
    row.updated_at = _now()
    await db.commit()
    await db.refresh(row)
    return _dto(row)


async def update_priority(db: AsyncSession, feedback_id: int, priority: int) -> dict:
    if priority is None:
        raise _bad("反馈优先级不能为空")
    if priority not in {1, 2, 3}:
        raise _bad("反馈优先级必须在 1 到 3 之间")
    row = await _get(db, feedback_id)
    row.priority = priority
    row.updated_at = _now()
    await db.commit()
    await db.refresh(row)
    return _dto(row)


async def reply(db: AsyncSession, admin_id: int, feedback_id: int, value: str) -> dict:
    if not value or not value.strip():
        raise _bad("管理员回复不能为空")
    if len(value.strip()) > 5000:
        raise _bad("管理员回复不能超过 5000 个字符")
    row = await _get(db, feedback_id)
    row.admin_id = admin_id
    row.admin_reply = value.strip()
    row.processed_at = _now()
    row.updated_at = _now()
    await db.commit()
    await db.refresh(row)
    return _dto(row)
