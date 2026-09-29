"""B9 administrator and public blog HTTP contracts."""

from typing import Annotated

from fastapi import Depends, File, Form, Header, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.management_auth import CurrentUser, require_role
from src.api.management_http import ApiResult, BusinessError, ManagementRouter, success
from src.application import blog
from src.config import settings
from src.database import get_db

admin_router = ManagementRouter(prefix="/api/v1/admin/blog", tags=["admin-blog"])
public_router = ManagementRouter(prefix="/api/v1/blog", tags=["blog"])
Admin = Annotated[CurrentUser, Depends(require_role("ADMIN"))]
DB = Annotated[AsyncSession, Depends(get_db)]


def _write_ready() -> None:
    if not settings.B9_BLOG_WRITES_ENABLED:
        raise BusinessError(503, "博客写入入口尚未切流", 503)


class CreatePost(BaseModel):
    title: str
    summary: str | None = None


class UpdatePost(BaseModel):
    title: str | None = None
    summary: str | None = None
    coverAssetId: int | None = None


class ContentBody(BaseModel):
    contentMarkdown: str


@admin_router.get("/posts")
async def posts(
    admin: Admin,
    db: DB,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    status: str | None = None,
):
    return success(await blog.admin_list(db, page, pageSize, status))


@admin_router.post("/posts")
async def create(body: CreatePost, admin: Admin, db: DB):
    _write_ready()
    return success(await blog.create(db, admin.user_id, body.title, body.summary))


@admin_router.get("/posts/{post_id}")
async def detail(post_id: int, admin: Admin, db: DB):
    return success(await blog.detail(db, post_id))


@admin_router.patch("/posts/{post_id}")
async def update(post_id: int, body: UpdatePost, admin: Admin, db: DB):
    _write_ready()
    return success(await blog.update(db, post_id, body.model_dump(exclude_unset=True)))


@admin_router.put("/posts/{post_id}/content")
async def save_content(post_id: int, body: ContentBody, admin: Admin, db: DB):
    _write_ready()
    return success(await blog.save_content(db, post_id, admin.user_id, body.contentMarkdown))


@admin_router.post("/posts/{post_id}/content/import")
@admin_router.post("/posts/{post_id}/content")
async def import_content(post_id: int, admin: Admin, db: DB, file: UploadFile = File(...)):
    _write_ready()
    content = await file.read(100 * 1024 * 1024 + 1)
    return success(
        await blog.import_content(db, post_id, admin.user_id, file.filename or "", content)
    )


@admin_router.post("/posts/{post_id}/publish")
async def publish(post_id: int, admin: Admin, db: DB):
    _write_ready()
    return success(await blog.publish(db, post_id, True))


@admin_router.post("/posts/{post_id}/unpublish")
async def unpublish(post_id: int, admin: Admin, db: DB):
    _write_ready()
    return success(await blog.publish(db, post_id, False))


@admin_router.delete("/posts/{post_id}")
async def delete(post_id: int, admin: Admin, db: DB):
    _write_ready()
    await blog.delete(db, post_id)
    return success()


@admin_router.get("/posts/{post_id}/assets")
async def assets(post_id: int, admin: Admin, db: DB, assetType: str | None = None):
    return success(await blog.assets(db, post_id, assetType))


@admin_router.post("/posts/{post_id}/assets")
async def upload_asset(
    post_id: int,
    admin: Admin,
    db: DB,
    assetType: str = Form(...),
    file: UploadFile = File(...),
):
    _write_ready()
    content = await file.read(10 * 1024 * 1024 + 1)
    return success(
        await blog.upload_asset(
            db,
            post_id,
            admin.user_id,
            assetType,
            file.filename or "",
            content,
            file.content_type,
        )
    )


@admin_router.delete("/posts/{post_id}/assets/{asset_id}")
async def delete_asset(post_id: int, asset_id: int, admin: Admin, db: DB):
    _write_ready()
    await blog.delete_asset(db, post_id, asset_id)
    return success()


@public_router.get("/posts")
async def public_posts(db: DB, page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100)):
    return success(await blog.public_list(db, page, pageSize))


@public_router.get("/posts/{slug}")
async def public_detail(slug: str, db: DB, if_none_match: str | None = Header(None)):
    try:
        row, cover_url, etag = await blog.public_snapshot(db, slug)
        headers = {"ETag": etag, "Cache-Control": "public, no-cache"}
        if if_none_match and any(
            value.strip() in {"*", etag, etag[2:]} for value in if_none_match.split(",")
        ):
            return Response(status_code=304, headers=headers)
        data = await blog.public_detail(row, cover_url)
        return JSONResponse(content=success(data).model_dump(mode="json"), headers=headers)
    except BusinessError as exc:
        return JSONResponse(
            status_code=exc.http_status,
            content=ApiResult(code=exc.code, message=exc.message).model_dump(),
            headers={"Cache-Control": "no-store"},
        )
