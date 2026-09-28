"""Compatibility endpoint for Java's generic OSS upload contract."""

import asyncio
import mimetypes
import os
import tempfile
from pathlib import Path

from botocore.exceptions import ClientError
from fastapi import File, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from src.api.management_http import BusinessError, ManagementRouter, success
from src.application.object_uploads import RULES, upload_object
from src.config import settings
from src.services.storage.factory import StorageFactory

router = ManagementRouter(prefix="/api/v1/oss-files", tags=["object-uploads"])


def _valid_public_key(key: str) -> bool:
    return bool(key) and not any(
        part in {"", ".", ".."} for part in key.split("/")
    ) and not any(char == "\\" or ord(char) < 32 for char in key)


@router.get("/public/{object_key:path}")
async def preview_public_object(object_key: str):
    """Serve only PUBLIC-bucket objects when this deployment owns the preview route."""
    if not settings.B2_PUBLIC_PREVIEW_ENABLED:
        raise BusinessError(503, "公开文件预览入口尚未切流", 503)
    if not _valid_public_key(object_key):
        raise BusinessError(404, "文件不存在", 404)
    fd, name = tempfile.mkstemp(prefix="tolink-public-preview-")
    os.close(fd)
    path = Path(name)
    try:
        storage = StorageFactory.get_storage()
        await asyncio.to_thread(storage.download_to_path,
                                settings.MINIO_PUBLIC_BUCKET, object_key, path)
    except ClientError as exc:
        path.unlink(missing_ok=True)
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NoSuchBucket"}:
            raise BusinessError(404, "文件不存在", 404) from exc
        raise BusinessError(503, "公开文件暂不可读取", 503) from exc
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise BusinessError(503, "公开文件暂不可读取", 503) from exc
    mime = mimetypes.guess_type(object_key)[0] or "application/octet-stream"
    return FileResponse(
        path, media_type=mime,
        headers={"Cache-Control": "public, max-age=2592000"},
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@router.post("/{biz_type}")
async def upload(biz_type: str, file: UploadFile = File(...)):
    if not settings.B2_GENERIC_UPLOAD_ENABLED:
        raise BusinessError(503, "通用上传入口尚未切流", 503)
    # Check the type before reading unbounded user input. Business validation still
    # preserves Java's empty-file-first ordering for supported types.
    rule = RULES.get(biz_type)
    if rule is None:
        first = await file.read(1)
        if not first:
            raise BusinessError(40001, "请选择要上传的文件", 400)
        raise BusinessError(40001, "上传业务类型不支持", 400)
    content = await file.read(rule.max_bytes + 1)
    result = await upload_object(biz_type, file.filename, content, file.content_type)
    return success(result.result)
