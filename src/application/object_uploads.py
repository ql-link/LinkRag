"""Java OSS business rules over the existing Python object storage adapter."""

from __future__ import annotations

import asyncio
import mimetypes
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.api.management_http import BusinessError
from src.config import settings
from src.services.storage.base import BaseObjectStorage
from src.services.storage.factory import StorageFactory

_IMAGE = frozenset({"jpg", "jpeg", "png", "gif", "webp"})
_FEEDBACK = _IMAGE | {"pdf", "doc", "docx", "txt", "md"}
_DOCUMENT = frozenset({"pdf", "doc", "docx", "txt", "md"})


@dataclass(frozen=True)
class UploadRule:
    place: str
    suffixes: frozenset[str] | None
    max_bytes: int


RULES: dict[str, UploadRule] = {
    "avatar": UploadRule("PUBLIC", _IMAGE, 5 * 1024 * 1024),
    "providerIcon": UploadRule("PUBLIC", _IMAGE, 5 * 1024 * 1024),
    "chatImage": UploadRule("PUBLIC", _IMAGE, 5 * 1024 * 1024),
    "document": UploadRule("RAW", _DOCUMENT, 20 * 1024 * 1024),
    "cert": UploadRule("PRIVATE", None, 5 * 1024 * 1024),
    "feedback": UploadRule("PUBLIC", _FEEDBACK, 10 * 1024 * 1024),
}


@dataclass(frozen=True)
class UploadedObject:
    bucket: str
    key: str
    result: str


def validate_upload(biz_type: str, filename: str | None, content: bytes) -> tuple[UploadRule, str]:
    """Follow Java's validation order so the first error remains compatible."""
    if not content:
        raise BusinessError(40001, "请选择要上传的文件", 400)
    rule = RULES.get(biz_type)
    if rule is None:
        raise BusinessError(40001, "上传业务类型不支持", 400)
    original = filename or ""
    last_dot = original.rfind(".")
    suffix = original[last_dot + 1 :].lower() if 0 <= last_dot < len(original) - 1 else ""
    if rule.suffixes is not None and suffix not in rule.suffixes:
        raise BusinessError(40001, "上传文件格式不支持", 400)
    if len(content) > rule.max_bytes:
        raise BusinessError(40001, f"上传大小请限制在 {rule.max_bytes // 1024 // 1024}M 以内", 400)
    return rule, suffix


def generate_object_key(biz_type: str, suffix: str) -> str:
    prefix = biz_type
    if biz_type == "feedback":
        prefix += "/" + datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y/%m")
    return f"{prefix}/{uuid4().hex}" + (f".{suffix}" if suffix else "")


def bucket_for(place: str) -> str:
    return {
        "PUBLIC": settings.MINIO_PUBLIC_BUCKET,
        "RAW": settings.MINIO_RAW_BUCKET,
        "PRIVATE": settings.MINIO_PRIVATE_BUCKET,
    }[place]


async def upload_object(
    biz_type: str,
    filename: str | None,
    content: bytes,
    content_type: str | None = None,
    *,
    object_key: str | None = None,
    storage: BaseObjectStorage | None = None,
) -> UploadedObject:
    rule, suffix = validate_upload(biz_type, filename, content)
    if object_key is not None and not object_key.strip():
        raise BusinessError(40001, "上传对象路径不能为空", 400)
    key = object_key or generate_object_key(biz_type, suffix)
    bucket = bucket_for(rule.place)
    adapter = storage or StorageFactory.get_storage()
    mime = content_type or mimetypes.guess_type(filename or "")[0] or "application/octet-stream"
    try:
        result = adapter.build_public_url(bucket, key) if rule.place == "PUBLIC" else key
        await asyncio.to_thread(adapter.upload_bytes, bucket, key, content, mime)
        # Java's MinIO provider returns only the object key for RAW and PRIVATE.
    except Exception as exc:
        raise BusinessError(50002, "文件上传失败", 500) from exc
    return UploadedObject(bucket, key, result)
