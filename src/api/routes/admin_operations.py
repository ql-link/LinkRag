"""B8 管理看板、运行配置与日志查询。"""

from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.management_auth import CurrentUser, require_role
from src.api.management_http import ApiResult, BusinessError, ManagementRouter, success
from src.application import admin_operations
from src.config import settings
from src.database import get_db

router = ManagementRouter(prefix="/api/v1/admin", tags=["admin-operations"])
Admin = Annotated[CurrentUser, Depends(require_role("ADMIN"))]
DB = Annotated[AsyncSession, Depends(get_db)]


class UpdateDocumentFileConfigRequest(BaseModel):
    maxSizeBytes: int
    allowedSuffixes: list[str]


@router.get("/users/dashboard")
async def dashboard(admin: Admin, db: DB, days: int = 30) -> ApiResult[dict]:
    return success(await admin_operations.user_dashboard(db, days))


@router.get("/document-file-config")
async def get_document_file_config(admin: Admin) -> ApiResult[dict]:
    return success(await admin_operations.get_upload_config())


@router.put("/document-file-config")
async def put_document_file_config(body: UpdateDocumentFileConfigRequest,
                                   admin: Admin) -> ApiResult[dict]:
    if not settings.B8_DOCUMENT_CONFIG_WRITES_ENABLED:
        raise BusinessError(503, "文档文件配置写入尚未切换", 503)
    return success(await admin_operations.update_upload_config(
        admin.user_id, body.maxSizeBytes, body.allowedSuffixes))


@router.get("/logs/labels")
async def log_labels(admin: Admin) -> ApiResult[dict]:
    return success(await admin_operations.log_labels())


@router.get("/logs")
async def logs(admin: Admin, service: str | None = None, level: str | None = None,
               trace_id: str | None = None, keyword: str | None = None,
               start_time: str | None = None, end_time: str | None = None,
               page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)) -> ApiResult[dict]:
    return success(await admin_operations.query_logs(
        service, level, trace_id, keyword, start_time, end_time, page, page_size))
