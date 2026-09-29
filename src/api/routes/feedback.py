"""Java-compatible B10 public submission and ADMIN feedback routes."""

from typing import Annotated

from fastapi import Depends, File, Form, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.management_auth import CurrentUser, require_role
from src.api.management_http import ApiResult, BusinessError, ManagementRouter, success
from src.application import feedback
from src.config import settings
from src.database import get_db

public_router = ManagementRouter(prefix="/api/v1/feedback", tags=["feedback"])
admin_router = ManagementRouter(prefix="/api/v1/admin/feedback", tags=["admin-feedback"])
Admin = Annotated[CurrentUser, Depends(require_role("ADMIN"))]
DB = Annotated[AsyncSession, Depends(get_db)]


def _writes_enabled() -> None:
    if not settings.B10_FEEDBACK_WRITES_ENABLED:
        raise BusinessError(503, "反馈写入入口尚未切流", 503)


class StatusRequest(BaseModel):
    status: str


class PriorityRequest(BaseModel):
    priority: int


class ReplyRequest(BaseModel):
    reply: str


@public_router.post("")
async def submit_feedback(
    db: DB,
    title: str = Form(...),
    content: str = Form(...),
    type: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> ApiResult[dict]:
    _writes_enabled()
    attachment = None
    if file is not None:
        attachment = await file.read(10 * 1024 * 1024 + 1)
    return success(
        await feedback.submit(
            db,
            type,
            title,
            content,
            file.filename if file else None,
            attachment,
            file.content_type if file else None,
        )
    )


@admin_router.get("")
async def list_feedback(
    admin: Admin,
    db: DB,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    status: str | None = None,
    type: str | None = None,
) -> ApiResult[dict]:
    return success(await feedback.list_feedback(db, page, pageSize, status, type))


@admin_router.get("/{feedback_id}")
async def detail(feedback_id: int, admin: Admin, db: DB) -> ApiResult[dict]:
    return success(await feedback.detail(db, feedback_id))


@admin_router.patch("/{feedback_id}/status")
async def update_status(
    feedback_id: int, body: StatusRequest, admin: Admin, db: DB
) -> ApiResult[dict]:
    _writes_enabled()
    return success(await feedback.update_status(db, feedback_id, body.status))


@admin_router.patch("/{feedback_id}/priority")
async def update_priority(
    feedback_id: int, body: PriorityRequest, admin: Admin, db: DB
) -> ApiResult[dict]:
    _writes_enabled()
    return success(await feedback.update_priority(db, feedback_id, body.priority))


@admin_router.patch("/{feedback_id}/reply")
async def reply(feedback_id: int, body: ReplyRequest, admin: Admin, db: DB) -> ApiResult[dict]:
    _writes_enabled()
    return success(await feedback.reply(db, admin.user_id, feedback_id, body.reply))
