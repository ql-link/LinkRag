"""B9 blog lifecycle over the existing PUBLIC object store and blog tables."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import certifi
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.management_http import BusinessError
from src.config import settings
from src.models.db_models import BlogAssetDB, BlogPostDB
from src.observability.logging import logger
from src.services.storage.base import BaseObjectStorage
from src.services.storage.factory import StorageFactory

_IMAGE_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}
_IMAGE_REF = re.compile(r'!\[([^\]]*)\]\((<[^>]+>|[^\s)]+)(\s+"[^"]*")?\)')
_MAX_IMAGE = 10 * 1024 * 1024
_MAX_CONTENT = 100 * 1024 * 1024


def _now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)


def _bad(message: str) -> BusinessError:
    return BusinessError(40001, message, 400)


def _missing() -> BusinessError:
    return BusinessError(404, "博客文章不存在", 404)


def _storage() -> BaseObjectStorage:
    return StorageFactory.get_storage()


async def _remove(storage: BaseObjectStorage, keys: list[str]) -> None:
    for key in keys:
        try:
            await asyncio.to_thread(
                storage.remove_object, settings.MINIO_PUBLIC_BUCKET, key
            )
        except Exception as exc:
            # Object cleanup is best effort after a successful DB transaction.
            logger.bind(
                event="blog_object_cleanup_failed",
                object_key=key,
                error_type=type(exc).__name__,
            ).warning("博客对象清理失败")


async def _read(storage: BaseObjectStorage, key: str) -> bytes:
    fd, name = tempfile.mkstemp(prefix="linkrag-blog-")
    os.close(fd)
    path = Path(name)
    try:
        await asyncio.to_thread(
            storage.download_to_path, settings.MINIO_PUBLIC_BUCKET, key, path
        )
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def _post_dto(
    row: BlogPostDB, *, detail: bool = False, markdown: str | None = None
) -> dict:
    result = {
        "id": row.id,
        "title": row.title,
        "slug": row.slug,
        "summary": row.summary,
        "contentObjectKey": row.content_object_key,
        "coverAssetId": row.cover_asset_id,
        "status": row.status,
        "publishedAt": row.published_at,
        "createdBy": row.created_by,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
    }
    if detail:
        result["contentMarkdown"] = markdown
    return result


def _public_dto(
    row: BlogPostDB, cover_url: str | None, markdown: str | None = None
) -> dict:
    result = {
        "id": row.id,
        "title": row.title,
        "slug": row.slug,
        "summary": row.summary,
        "coverAssetId": row.cover_asset_id,
        "coverPublicUrl": cover_url,
        "publishedAt": row.published_at,
    }
    if markdown is not None:
        result["contentMarkdown"] = markdown
    return result


def _asset_dto(row: BlogAssetDB) -> dict:
    result = {
        "id": row.id,
        "postId": row.post_id,
        "assetType": row.asset_type,
        "originalFilename": row.original_filename,
        "contentType": row.content_type,
        "fileSize": row.file_size,
        "objectKey": row.object_key,
        "publicUrl": row.public_url,
        "createdBy": row.created_by,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
        "markdownText": None,
    }
    if row.asset_type == "CONTENT_IMAGE":
        alt = row.original_filename.replace("[", "").replace("]", "")
        result["markdownText"] = f"![{alt}]({row.public_url})"
    return result


async def _post(db: AsyncSession, post_id: int, *, lock: bool = False) -> BlogPostDB:
    query = select(BlogPostDB).where(
        BlogPostDB.id == post_id, BlogPostDB.is_deleted.is_(False)
    )
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None:
        raise _missing()
    return row


async def _cover(db: AsyncSession, row: BlogPostDB) -> str | None:
    if row.cover_asset_id is None:
        return None
    asset = await db.scalar(
        select(BlogAssetDB).where(
            BlogAssetDB.id == row.cover_asset_id,
            BlogAssetDB.post_id == row.id,
            BlogAssetDB.is_deleted.is_(False),
        )
    )
    return asset.public_url if asset else None


async def create(
    db: AsyncSession, admin_id: int, title: str, summary: str | None
) -> dict:
    title = (title or "").strip()
    if not title or len(title) > 255:
        raise _bad("博客标题不能为空且不能超过 255 个字符")
    if summary is not None and len(summary) > 1000:
        raise _bad("博客摘要不能超过 1000 个字符")
    now = _now()
    row = BlogPostDB(
        title=title,
        slug=uuid4().hex,
        summary=summary.strip() or None if summary else None,
        status="DRAFT",
        created_by=admin_id,
        is_deleted=False,
        deleted_seq=0,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _post_dto(row, detail=True)


async def admin_list(
    db: AsyncSession, page: int, size: int, status: str | None
) -> dict:
    clauses = [BlogPostDB.is_deleted.is_(False)]
    if status and status.strip():
        value = status.strip().upper()
        if value not in {"DRAFT", "PUBLISHED"}:
            raise _bad("博客状态不支持")
        clauses.append(BlogPostDB.status == value)
    total = (
        await db.scalar(select(func.count()).select_from(BlogPostDB).where(*clauses))
        or 0
    )
    rows = (
        await db.scalars(
            select(BlogPostDB)
            .where(*clauses)
            .order_by(BlogPostDB.updated_at.desc(), BlogPostDB.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).all()
    return {
        "items": [_post_dto(row) for row in rows],
        "total": int(total),
        "page": page,
        "pageSize": size,
        "totalPages": (int(total) + size - 1) // size,
    }


async def detail(db: AsyncSession, post_id: int) -> dict:
    row = await _post(db, post_id)
    markdown = None
    if row.content_object_key:
        try:
            markdown = (await _read(_storage(), row.content_object_key)).decode("utf-8")
        except Exception:
            # Java management detail is still readable when an old OSS object is missing.
            markdown = None
    return _post_dto(row, detail=True, markdown=markdown)


async def update(db: AsyncSession, post_id: int, changes: dict) -> dict:
    row = await _post(db, post_id, lock=True)
    if not any(
        changes.get(name) is not None for name in ("title", "summary", "coverAssetId")
    ):
        raise _bad("请至少提供一个需要更新的字段")
    if changes.get("title") is not None:
        title = (changes["title"] or "").strip()
        if not title or len(title) > 255:
            raise _bad("博客标题不能为空且不能超过 255 个字符")
        row.title = title
    if changes.get("summary") is not None:
        summary = changes["summary"]
        if summary is not None and len(summary) > 1000:
            raise _bad("博客摘要不能超过 1000 个字符")
        row.summary = summary.strip() or None
    if changes.get("coverAssetId") is not None:
        cover_id = changes["coverAssetId"]
        if cover_id is not None:
            asset = await db.scalar(
                select(BlogAssetDB).where(
                    BlogAssetDB.id == cover_id,
                    BlogAssetDB.post_id == post_id,
                    BlogAssetDB.asset_type == "COVER",
                    BlogAssetDB.is_deleted.is_(False),
                )
            )
            if asset is None:
                raise _bad("封面资源不属于当前文章")
        row.cover_asset_id = cover_id
    row.updated_at = _now()
    await db.commit()
    await db.refresh(row)
    return await detail(db, post_id)


def _validate_image(filename: str, content: bytes, mime: str | None) -> tuple[str, str]:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    expected = _IMAGE_TYPES.get(suffix)
    normalized_mime = mime.split(";", 1)[0].strip().lower() if mime else ""
    if expected is None or not normalized_mime or normalized_mime != expected:
        raise _bad("博客图片格式不支持")
    if not content or len(content) > _MAX_IMAGE:
        raise _bad("博客图片不能为空且不能超过 10MB")
    return suffix, expected


def _sniff_image_suffix(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "webp"
    return None


def _fetch_remote_image(url: str) -> tuple[str, bytes, str] | None:
    """Fetch only a resolved public IP while retaining the original TLS hostname."""
    current = url
    for _ in range(4):
        connection = None
        try:
            parsed = urlsplit(current)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                return None
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            if not addresses or any(
                not ipaddress.ip_address(item[4][0]).is_global for item in addresses
            ):
                return None
            pinned_ip = addresses[0][4][0]
            if parsed.scheme == "https":
                context = ssl.create_default_context(cafile=certifi.where())
                connection = http.client.HTTPSConnection(
                    host, port, timeout=10, context=context
                )
            else:
                connection = http.client.HTTPConnection(host, port, timeout=10)

            def connect_pinned(_address, timeout, source_address):
                return socket.create_connection(
                    (pinned_ip, port), timeout, source_address
                )

            connection._create_connection = connect_pinned
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            connection.request("GET", target, headers={"Accept": "image/*"})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    return None
                current = urljoin(current, location)
                continue
            if response.status != 200:
                return None
            length = response.getheader("Content-Length")
            if length and int(length) > _MAX_IMAGE:
                return None
            data = response.read(_MAX_IMAGE + 1)
            if not data or len(data) > _MAX_IMAGE:
                return None
            mime = (response.getheader("Content-Type") or "").split(";", 1)[0].lower()
            suffix = "jpg" if mime == "image/jpeg" else mime.removeprefix("image/")
            if suffix not in _IMAGE_TYPES:
                suffix = _sniff_image_suffix(data) or ""
            if suffix not in _IMAGE_TYPES:
                suffix = parsed.path.rsplit(".", 1)[-1].lower()
            if suffix not in _IMAGE_TYPES:
                return None
            if mime in {"", "application/octet-stream"}:
                mime = _IMAGE_TYPES[suffix]
            if _IMAGE_TYPES[suffix] != mime:
                return None
            filename = f"remote.{suffix}"
            _validate_image(filename, data, mime)
            return filename, data, mime
        except (OSError, ValueError, http.client.HTTPException, BusinessError):
            return None
        finally:
            if connection is not None:
                connection.close()
    return None


async def _safe_remote_image(url: str) -> tuple[str, bytes, str] | None:
    """Keep remote downloads off the event loop and preserve Java's best effort rule."""
    return await asyncio.to_thread(_fetch_remote_image, url)


async def _upload_asset(
    db: AsyncSession,
    post_id: int,
    admin_id: int,
    asset_type: str,
    filename: str,
    content: bytes,
    mime: str | None,
    storage: BaseObjectStorage,
) -> BlogAssetDB:
    suffix, detected = _validate_image(filename, content, mime)
    key = f"blog/{post_id}/{'cover' if asset_type == 'COVER' else 'images'}/{uuid4().hex}.{suffix}"
    public_url = storage.build_public_url(settings.MINIO_PUBLIC_BUCKET, key)
    await asyncio.to_thread(
        storage.upload_bytes, settings.MINIO_PUBLIC_BUCKET, key, content, detected
    )
    now = _now()
    return BlogAssetDB(
        post_id=post_id,
        asset_type=asset_type,
        original_filename=filename[:255],
        content_type=detected,
        file_size=len(content),
        object_key=key,
        public_url=public_url,
        created_by=admin_id,
        is_deleted=False,
        created_at=now,
        updated_at=now,
    )


async def upload_asset(
    db: AsyncSession,
    post_id: int,
    admin_id: int,
    asset_type: str,
    filename: str,
    content: bytes,
    mime: str | None,
) -> dict:
    kind = (asset_type or "").strip().upper()
    if kind not in {"COVER", "CONTENT_IMAGE"}:
        raise _bad("博客资源类型不支持")
    row = await _post(db, post_id, lock=True)
    storage = _storage()
    asset = await _upload_asset(
        db, post_id, admin_id, kind, filename, content, mime, storage
    )
    cleanup: list[str] = []
    try:
        db.add(asset)
        await db.flush()
        if kind == "COVER":
            if row.cover_asset_id:
                old = await db.scalar(
                    select(BlogAssetDB).where(
                        BlogAssetDB.id == row.cover_asset_id,
                        BlogAssetDB.post_id == post_id,
                        BlogAssetDB.is_deleted.is_(False),
                    )
                )
                if old:
                    old.is_deleted = True
                    cleanup.append(old.object_key)
            row.cover_asset_id = asset.id
        row.updated_at = _now()
        await db.commit()
    except Exception:
        await db.rollback()
        await _remove(storage, [asset.object_key])
        raise
    await _remove(storage, cleanup)
    return _asset_dto(asset)


async def assets(
    db: AsyncSession, post_id: int, asset_type: str | None = None
) -> list[dict]:
    await _post(db, post_id)
    clauses = [BlogAssetDB.post_id == post_id, BlogAssetDB.is_deleted.is_(False)]
    if asset_type and asset_type.strip():
        value = asset_type.strip().upper()
        if value not in {"COVER", "CONTENT_IMAGE"}:
            raise _bad("资源类型不支持")
        clauses.append(BlogAssetDB.asset_type == value)
    rows = (
        await db.scalars(
            select(BlogAssetDB)
            .where(*clauses)
            .order_by(BlogAssetDB.created_at.desc(), BlogAssetDB.id.desc())
        )
    ).all()
    return [_asset_dto(row) for row in rows]


async def delete_asset(db: AsyncSession, post_id: int, asset_id: int) -> None:
    post = await _post(db, post_id, lock=True)
    asset = await db.scalar(
        select(BlogAssetDB)
        .where(
            BlogAssetDB.id == asset_id,
            BlogAssetDB.post_id == post_id,
            BlogAssetDB.is_deleted.is_(False),
        )
        .with_for_update()
    )
    if asset is None:
        raise BusinessError(404, "博客资源不存在", 404)
    if asset.asset_type == "CONTENT_IMAGE" and post.content_object_key:
        markdown = (await _read(_storage(), post.content_object_key)).decode("utf-8")
        if (
            asset.public_url in markdown
            or f"/{settings.MINIO_PUBLIC_BUCKET}/{asset.object_key}" in markdown
        ):
            raise _bad("博客资源仍被正文引用")
    asset.is_deleted = True
    if post.cover_asset_id == asset.id:
        post.cover_asset_id = None
    post.updated_at = _now()
    await db.commit()
    await _remove(_storage(), [asset.object_key])


async def save_content(
    db: AsyncSession, post_id: int, admin_id: int, markdown: str
) -> dict:
    if not markdown or not markdown.strip():
        raise _bad("博客正文不能为空")
    if len(markdown.encode("utf-8")) > _MAX_CONTENT:
        raise _bad("博客正文不能超过 100MB")
    post = await _post(db, post_id, lock=True)
    storage = _storage()
    known = (
        await db.scalars(
            select(BlogAssetDB).where(
                BlogAssetDB.post_id == post_id, BlogAssetDB.is_deleted.is_(False)
            )
        )
    ).all()
    known_urls = {
        url
        for asset in known
        for url in (
            asset.public_url,
            f"/{settings.MINIO_PUBLIC_BUCKET}/{asset.object_key}",
        )
    }
    created_keys: list[str] = []
    try:
        for match in reversed(list(_IMAGE_REF.finditer(markdown))):
            url = match.group(2).strip("<>")
            if url in known_urls:
                continue
            if url.startswith("data:"):
                header, sep, encoded = url.partition(",")
                mime_match = re.fullmatch(
                    r"data:(image/(?:jpeg|png|gif|webp));base64", header, re.I
                )
                if (
                    not sep
                    or mime_match is None
                    or len(encoded) > _MAX_IMAGE * 4 // 3 + 8
                ):
                    raise _bad("Markdown 图片数据不合法")
                try:
                    content = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise _bad("Markdown 图片数据不合法") from exc
                suffix = (
                    "jpg"
                    if mime_match.group(1).lower() == "image/jpeg"
                    else mime_match.group(1).split("/")[1].lower()
                )
                asset = await _upload_asset(
                    db,
                    post_id,
                    admin_id,
                    "CONTENT_IMAGE",
                    f"inline.{suffix}",
                    content,
                    mime_match.group(1),
                    storage,
                )
                created_keys.append(asset.object_key)
                db.add(asset)
                markdown = (
                    markdown[: match.start(2)]
                    + asset.public_url
                    + markdown[match.end(2) :]
                )
            elif url.startswith(("https://", "http://")):
                remote = await _safe_remote_image(url)
                if remote is not None:
                    asset = await _upload_asset(
                        db,
                        post_id,
                        admin_id,
                        "CONTENT_IMAGE",
                        remote[0],
                        remote[1],
                        remote[2],
                        storage,
                    )
                    created_keys.append(asset.object_key)
                    db.add(asset)
                    markdown = (
                        markdown[: match.start(2)]
                        + asset.public_url
                        + markdown[match.end(2) :]
                    )
            else:
                raise _bad("Markdown 图片必须使用当前文章资源或公开链接")
        key = f"blog/{post_id}/content/{uuid4().hex}.md"
        await asyncio.to_thread(
            storage.upload_bytes,
            settings.MINIO_PUBLIC_BUCKET,
            key,
            markdown.encode("utf-8"),
            "text/markdown; charset=utf-8",
        )
        created_keys.append(key)
        old_key = post.content_object_key
        post.content_object_key = key
        post.updated_at = _now()
        await db.commit()
    except Exception:
        await db.rollback()
        await _remove(storage, created_keys)
        raise
    if old_key:
        await _remove(storage, [old_key])
    return await detail(db, post_id)


async def import_content(
    db: AsyncSession, post_id: int, admin_id: int, filename: str, content: bytes
) -> dict:
    if not filename.lower().endswith((".md", ".markdown")):
        raise _bad("仅支持 Markdown 文件")
    try:
        markdown = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _bad("Markdown 文件必须为 UTF-8 编码") from exc
    return await save_content(db, post_id, admin_id, markdown)


async def publish(db: AsyncSession, post_id: int, published: bool) -> dict:
    row = await _post(db, post_id, lock=True)
    if published:
        if not row.content_object_key:
            raise _bad("请先保存博客正文")
        try:
            await _read(_storage(), row.content_object_key)
        except Exception as exc:
            raise _bad("博客正文对象不存在") from exc
        if row.published_at is None:
            row.published_at = _now()
    row.status = "PUBLISHED" if published else "DRAFT"
    row.updated_at = _now()
    await db.commit()
    await db.refresh(row)
    return await detail(db, post_id)


async def delete(db: AsyncSession, post_id: int) -> None:
    row = await _post(db, post_id, lock=True)
    assets = (
        await db.scalars(
            select(BlogAssetDB).where(
                BlogAssetDB.post_id == post_id, BlogAssetDB.is_deleted.is_(False)
            )
        )
    ).all()
    keys = [asset.object_key for asset in assets]
    if row.content_object_key:
        keys.append(row.content_object_key)
    for asset in assets:
        asset.is_deleted = True
    row.is_deleted = True
    row.deleted_seq = row.id
    row.updated_at = _now()
    await db.commit()
    await _remove(_storage(), keys)


async def public_list(db: AsyncSession, page: int, size: int) -> dict:
    clauses = [BlogPostDB.is_deleted.is_(False), BlogPostDB.status == "PUBLISHED"]
    total = (
        await db.scalar(select(func.count()).select_from(BlogPostDB).where(*clauses))
        or 0
    )
    rows = (
        await db.scalars(
            select(BlogPostDB)
            .where(*clauses)
            .order_by(BlogPostDB.published_at.desc(), BlogPostDB.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).all()
    return {
        "items": [_public_dto(row, await _cover(db, row)) for row in rows],
        "total": int(total),
        "page": page,
        "pageSize": size,
        "totalPages": (int(total) + size - 1) // size,
    }


async def public_snapshot(
    db: AsyncSession, slug: str
) -> tuple[BlogPostDB, str | None, str]:
    if not re.fullmatch(r"[0-9a-f]{32}", slug):
        raise _bad("slug格式不合法")
    row = await db.scalar(
        select(BlogPostDB).where(
            BlogPostDB.slug == slug,
            BlogPostDB.is_deleted.is_(False),
            BlogPostDB.status == "PUBLISHED",
        )
    )
    if row is None:
        raise _missing()
    cover_url = await _cover(db, row)
    canonical = {
        "format": "blog-public-detail-1",
        "id": row.id,
        "title": row.title,
        "slug": row.slug,
        "summary": row.summary,
        "contentObjectKey": row.content_object_key,
        "coverAssetId": row.cover_asset_id,
        "coverPublicUrl": cover_url,
        "status": row.status,
        "publishedAt": row.published_at.isoformat() if row.published_at else None,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return row, cover_url, 'W/"' + digest + '"'


async def public_detail(row: BlogPostDB, cover_url: str | None) -> dict:
    markdown = ""
    if row.content_object_key:
        try:
            markdown = (await _read(_storage(), row.content_object_key)).decode("utf-8")
        except Exception as exc:
            raise BusinessError(50003, "读取Markdown正文失败", 500) from exc
    return _public_dto(row, cover_url, markdown=markdown)
