"""B9/B10 persistence, public visibility and object compensation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from src.api.management_auth import require_login
from src.api.management_http import BusinessError
from src.api.routes import blog as blog_routes
from src.api.routes import feedback as feedback_routes
from src.application import blog, feedback
from src.config import settings
from src.database import get_db
from src.models.db_models import BlogAssetDB, BlogPostDB, UserFeedbackDB


@compiles(BigInteger, "sqlite")
def _bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.removed = []

    def upload_bytes(self, bucket, key, data, mime):
        self.objects[(bucket, key)] = data

    def download_to_path(self, bucket, key, path):
        path.write_bytes(self.objects[(bucket, key)])

    def remove_object(self, bucket, key):
        self.removed.append((bucket, key))
        self.objects.pop((bucket, key), None)

    def build_public_url(self, bucket, key):
        return f"https://public.example/{key}"


@pytest.fixture
async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(
            BlogPostDB.metadata.create_all,
            tables=[
                BlogPostDB.__table__,
                BlogAssetDB.__table__,
                UserFeedbackDB.__table__,
            ],
        )
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def storage(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr(blog.StorageFactory, "get_storage", lambda: fake)
    monkeypatch.setattr(feedback.StorageFactory, "get_storage", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_blog_publish_public_etag_and_asset_reference(database, storage):
    async with database() as db:
        post = await blog.create(db, 7, "首篇", "摘要")
        assert post["status"] == "DRAFT"
        assert (await blog.public_list(db, 1, 20))["total"] == 0
        with pytest.raises(BusinessError):
            await blog.publish(db, post["id"], True)
        png = b"\x89PNG\r\n\x1a\n" + b"image"
        asset = await blog.upload_asset(
            db, post["id"], 7, "CONTENT_IMAGE", "a.png", png, "image/png"
        )
        await blog.save_content(db, post["id"], 7, f"# 正文\n![图]({asset['publicUrl']})")
        with pytest.raises(BusinessError):
            await blog.delete_asset(db, post["id"], asset["id"])
        await blog.publish(db, post["id"], True)
        snapshot, cover_url, etag = await blog.public_snapshot(db, post["slug"])
        data = await blog.public_detail(snapshot, cover_url)
        assert "# 正文" in data["contentMarkdown"] and etag.startswith('W/"')
        assert set(data) == {
            "id",
            "title",
            "slug",
            "summary",
            "coverAssetId",
            "coverPublicUrl",
            "publishedAt",
            "contentMarkdown",
        }
        assert (await blog.public_list(db, 1, 20))["total"] == 1
        await blog.publish(db, post["id"], False)
        with pytest.raises(BusinessError) as error:
            await blog.public_snapshot(db, post["slug"])
        assert error.value.http_status == 404
        await blog.delete(db, post["id"])
        assert (await blog.admin_list(db, 1, 20, None))["total"] == 0
        assert storage.removed


@pytest.mark.asyncio
async def test_blog_inline_image_and_invalid_reference_rollback(database, storage):
    async with database() as db:
        post = await blog.create(db, 7, "图文", None)
        with pytest.raises(BusinessError):
            await blog.save_content(db, post["id"], 7, "![bad](file:///etc/passwd)")
        assert (await blog.detail(db, post["id"]))["contentObjectKey"] is None
        import base64

        png = b"\x89PNG\r\n\x1a\n" + b"image"
        result = await blog.save_content(
            db,
            post["id"],
            7,
            "![图](data:image/png;base64," + base64.b64encode(png).decode() + ")",
        )
        assert "data:" not in result["contentMarkdown"]
        assert len(await blog.assets(db, post["id"])) == 1
        with pytest.raises(BusinessError):
            await blog.assets(db, post["id"], "BAD_TYPE")
        assert len(await blog.assets(db, post["id"], "content_image")) == 1


@pytest.mark.asyncio
async def test_blog_remote_image_safety_and_best_effort(database, storage, monkeypatch):
    monkeypatch.setattr(
        blog.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 80))],
    )
    assert await blog._safe_remote_image("http://localhost/private.png") is None
    async with database() as db:
        post = await blog.create(db, 7, "远程图", None)
        saved = await blog.save_content(
            db, post["id"], 7, '![图](http://localhost/private.png "标题")'
        )
        assert "http://localhost/private.png" in saved["contentMarkdown"]
        assert await blog.assets(db, post["id"]) == []

        async def allowed_image(_url):
            return "remote.png", b"\x89PNG\r\n\x1a\nimage", "image/png"

        monkeypatch.setattr(blog, "_safe_remote_image", allowed_image)
        imported = await blog.save_content(
            db, post["id"], 7, "![图](https://example.com/image.png)"
        )
        assert "https://example.com/image.png" not in imported["contentMarkdown"]
        assert len(await blog.assets(db, post["id"], "CONTENT_IMAGE")) == 1


def test_blog_remote_image_connects_to_validated_ip(monkeypatch):
    resolved = []
    connected = []
    png = b"\x89PNG\r\n\x1a\n" + b"image"

    def resolve(host, port, **_kwargs):
        resolved.append((host, port))
        return [(2, 1, 6, "", ("93.184.215.14", port))]

    class Response:
        status = 200

        def getheader(self, name):
            return "image/png" if name == "Content-Type" else None

        def read(self, _limit):
            return png

    class Connection:
        def __init__(self, host, port, **_kwargs):
            self.host = host
            self.port = port

        def request(self, _method, _target, **_kwargs):
            self._create_connection((self.host, self.port), 10, None)

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(blog.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(
        blog.socket,
        "create_connection",
        lambda address, *_args: connected.append(address),
    )
    monkeypatch.setattr(blog.http.client, "HTTPConnection", Connection)
    assert blog._fetch_remote_image("http://example.com/image.png") == (
        "remote.png",
        png,
        "image/png",
    )
    assert resolved == [("example.com", 80)]
    assert connected == [("93.184.215.14", 80)]


def test_blog_remote_image_rejects_private_redirect(monkeypatch):
    resolved = []

    def resolve(host, port, **_kwargs):
        resolved.append(host)
        ip = "93.184.215.14" if host == "example.com" else "127.0.0.1"
        return [(2, 1, 6, "", (ip, port))]

    class Response:
        status = 302

        def getheader(self, name):
            return "http://localhost/private" if name == "Location" else None

    class Connection:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(blog.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(blog.http.client, "HTTPConnection", Connection)
    assert blog._fetch_remote_image("http://example.com/image.png") is None
    assert resolved == ["example.com", "localhost"]


@pytest.mark.asyncio
async def test_feedback_commit_failure_cleans_uploaded_object(storage):
    class FailingDB:
        def add(self, _row):
            pass

        async def commit(self):
            raise RuntimeError("database unavailable")

        async def rollback(self):
            pass

    with pytest.raises(RuntimeError):
        await feedback.submit(
            FailingDB(), "BUG", "标题", "内容", "sample.txt", b"hello", "text/plain"
        )
    assert storage.objects == {}
    assert len(storage.removed) == 1


@pytest.mark.asyncio
async def test_feedback_submission_admin_workflow_and_attachment(database, storage):
    async with database() as db:
        with pytest.raises(BusinessError):
            await feedback.submit(db, "BUG", " ", "content")
        item = await feedback.submit(
            db, "bug", "标题 ", " 内容 ", "sample.txt", b"hello", "text/plain"
        )
        assert item["status"] == "PENDING" and item["attachmentUrl"]
        assert (await feedback.list_feedback(db, 1, 20, "pending", "bug"))["total"] == 1
        assert (await feedback.update_priority(db, item["id"], 1))["priority"] == 1
        assert (await feedback.update_status(db, item["id"], "RESOLVED"))["processedAt"]
        answer = await feedback.reply(db, 7, item["id"], " 已处理 ")
        assert answer["adminId"] == 7 and answer["adminReply"] == "已处理"
        with pytest.raises(BusinessError):
            await feedback.update_priority(db, item["id"], 4)


@pytest.mark.asyncio
async def test_http_gates_permissions_and_public_cache(database, storage, monkeypatch):
    app = FastAPI()
    app.include_router(blog_routes.admin_router)
    app.include_router(blog_routes.public_router)
    app.include_router(feedback_routes.admin_router)
    app.include_router(feedback_routes.public_router)
    app.dependency_overrides[require_login] = lambda: SimpleNamespace(user_id=7, role="USER")

    async def db_override():
        async with database() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (
            await client.post("/api/v1/admin/blog/posts", json={"title": "x"})
        ).status_code == 403
        assert (
            await client.post("/api/v1/feedback", data={"title": "x", "content": "y"})
        ).status_code == 503

    app.dependency_overrides[require_login] = lambda: SimpleNamespace(user_id=7, role="ADMIN")
    monkeypatch.setattr(settings, "B9_BLOG_WRITES_ENABLED", True)
    monkeypatch.setattr(settings, "B10_FEEDBACK_WRITES_ENABLED", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        post = (await client.post("/api/v1/admin/blog/posts", json={"title": "x"})).json()["data"]
        assert (
            await client.put(
                f"/api/v1/admin/blog/posts/{post['id']}/content",
                json={"contentMarkdown": "正文"},
            )
        ).status_code == 200
        assert (
            await client.post(f"/api/v1/admin/blog/posts/{post['id']}/publish")
        ).status_code == 200
        first = await client.get(f"/api/v1/blog/posts/{post['slug']}")
        assert first.status_code == 200 and first.headers["cache-control"] == "public, no-cache"
        second = await client.get(
            f"/api/v1/blog/posts/{post['slug']}",
            headers={"If-None-Match": first.headers["etag"]},
        )
        assert second.status_code == 304
        # Conditional requests must not need object storage; Java returns 304 first.
        storage.objects.clear()
        conditional = await client.get(
            f"/api/v1/blog/posts/{post['slug']}",
            headers={"If-None-Match": first.headers["etag"]},
        )
        assert conditional.status_code == 304
        missing = await client.get(f"/api/v1/blog/posts/{post['slug']}")
        assert missing.status_code == 500 and missing.json()["code"] == 50003
        assert missing.headers["cache-control"] == "no-store"
        assert (
            await client.post("/api/v1/feedback", data={"title": "x", "content": "y"})
        ).status_code == 200
