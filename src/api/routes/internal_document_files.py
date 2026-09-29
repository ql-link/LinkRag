"""Service-token protected original-file stream using the existing storage adapter."""

from __future__ import annotations

import asyncio
import secrets
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from starlette.background import BackgroundTask

from src.api.management_http import BusinessError, ManagementRouter
from src.config import settings
from src.database import get_db_context
from src.services.storage.factory import StorageFactory

router = ManagementRouter(prefix="/api/v1/internal/files", tags=["internal-files"])


@router.get("/{file_id}/content")
async def download(file_id: int, request: Request):
    expected = settings.B5_INTERNAL_FILE_SERVICE_TOKEN
    authorization = request.headers.get("authorization", "")
    if not expected or not secrets.compare_digest(authorization, "Bearer " + expected):
        raise BusinessError(401, "服务鉴权失败", 401)
    async with get_db_context() as db:
        row = (
            (
                await db.execute(
                    text("""
            SELECT original_filename,content_type,bucket_name,object_key
            FROM document_original_file
            WHERE id=:fid AND is_deleted=0 AND is_upload_success=1
        """),
                    {"fid": file_id},
                )
            )
            .mappings()
            .one_or_none()
        )
    if row is None or not row["object_key"]:
        raise BusinessError(404, "文件不存在", 404)
    temporary = TemporaryDirectory(prefix="tolink-original-file-")
    path = Path(temporary.name) / "original"
    try:
        await asyncio.to_thread(
            StorageFactory.get_storage().download_to_path,
            row["bucket_name"],
            row["object_key"],
            path,
        )
        if not path.is_file():
            raise FileNotFoundError
    except Exception as exc:
        temporary.cleanup()
        raise BusinessError(404, "文件不存在", 404) from exc
    return FileResponse(
        path,
        filename=row["original_filename"],
        media_type=row["content_type"] or "application/octet-stream",
        background=BackgroundTask(temporary.cleanup),
    )
