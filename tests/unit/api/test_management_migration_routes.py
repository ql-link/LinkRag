"""HTTP wiring of migrated routes without external services."""

from contextlib import asynccontextmanager

import httpx
import pytest
from botocore.exceptions import ClientError
from fastapi import FastAPI

from src.api.management_auth import CurrentUser, require_login
from src.api.routes import datasets as dataset_routes
from src.api.routes import internal_document_files, object_uploads
from src.config import settings


class FakeStorage:
    def __init__(self):
        self.uploads = []

    def upload_bytes(self, bucket, key, content, content_type):
        self.uploads.append((bucket, key, content, content_type))

    def build_public_url(self, _bucket, key):
        return f"https://cdn.example.invalid/{key}"

    def download_to_path(self, bucket, key, destination):
        assert bucket == "public"
        assert key == "avatar/probe.png"
        destination.write_bytes(b"image-data")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "biz_type,bucket,public",
    [
        ("avatar", "public", True),
        ("providerIcon", "public", True),
        ("chatImage", "public", True),
        ("document", "raw", False),
        ("cert", "private", False),
        ("feedback", "public", True),
    ],
)
async def test_b2_multipart_http_uses_shared_storage(monkeypatch, biz_type, bucket, public):
    from src.application import object_uploads as uploads

    storage = FakeStorage()
    monkeypatch.setattr(settings, "B2_GENERIC_UPLOAD_ENABLED", True)
    monkeypatch.setattr(settings, "MINIO_PUBLIC_BUCKET", "public")
    monkeypatch.setattr(settings, "MINIO_RAW_BUCKET", "raw")
    monkeypatch.setattr(settings, "MINIO_PRIVATE_BUCKET", "private")
    monkeypatch.setattr(uploads.StorageFactory, "get_storage", lambda: storage)
    app = FastAPI()
    app.include_router(object_uploads.router)
    app.dependency_overrides[require_login] = lambda: CurrentUser(7, "USER")
    suffix = "pdf" if biz_type == "document" else "pem" if biz_type == "cert" else "png"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/oss-files/{biz_type}",
            files={"file": (f"probe.{suffix}", b"probe", "application/octet-stream")},
        )
    assert response.status_code == 200
    assert response.json()["code"] == 200
    assert len(storage.uploads) == 1
    actual_bucket, key, content, _mime = storage.uploads[0]
    assert actual_bucket == bucket
    assert key.startswith(f"{biz_type}/")
    assert content == b"probe"
    assert response.json()["data"] == (f"https://cdn.example.invalid/{key}" if public else key)


@pytest.mark.asyncio
async def test_b2_multipart_validation_and_disabled_gate(monkeypatch):
    app = FastAPI()
    app.include_router(object_uploads.router)
    app.dependency_overrides[require_login] = lambda: CurrentUser(7, "USER")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        monkeypatch.setattr(settings, "B2_GENERIC_UPLOAD_ENABLED", False)
        disabled = await client.post("/api/v1/oss-files/avatar", files={"file": ("a.png", b"a")})
        assert disabled.status_code == 503
        monkeypatch.setattr(settings, "B2_GENERIC_UPLOAD_ENABLED", True)
        bad = await client.post("/api/v1/oss-files/avatar", files={"file": ("a.exe", b"a")})
        assert bad.status_code == 400
        assert bad.json()["code"] == 40001


@pytest.mark.asyncio
async def test_b2_generic_upload_rejects_anonymous(monkeypatch):
    monkeypatch.setattr(settings, "B2_GENERIC_UPLOAD_ENABLED", True)
    app = FastAPI()
    app.include_router(object_uploads.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/oss-files/avatar", files={"file": ("a.png", b"a")})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_b2_public_preview_reads_only_public_bucket(monkeypatch):
    from src.api.routes import object_uploads as route

    storage = FakeStorage()
    monkeypatch.setattr(settings, "MINIO_PUBLIC_BUCKET", "public")
    monkeypatch.setattr(settings, "B2_PUBLIC_PREVIEW_ENABLED", True)
    monkeypatch.setattr(route.StorageFactory, "get_storage", lambda: storage)
    app = FastAPI()
    app.include_router(object_uploads.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.get("/api/v1/oss-files/public/avatar/probe.png")
        assert result.status_code == 200
        assert result.content == b"image-data"
        assert result.headers["content-type"] == "image/png"
        assert result.headers["cache-control"] == "public, max-age=2592000"
        monkeypatch.setattr(settings, "B2_PUBLIC_PREVIEW_ENABLED", False)
        blocked = await client.get("/api/v1/oss-files/public/avatar/probe.png")
        assert blocked.status_code == 503
    assert route._valid_public_key("avatar/file.png")
    for key in ("", "../private/key", "avatar//key", "avatar/./key", "avatar\\key"):
        assert not route._valid_public_key(key)


@pytest.mark.asyncio
async def test_b2_public_preview_missing_object_is_404(monkeypatch):
    from src.api.routes import object_uploads as route

    class MissingStorage:
        def download_to_path(self, bucket, key, destination):
            assert bucket == "public"
            destination.write_bytes(b"partial")
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

    monkeypatch.setattr(settings, "MINIO_PUBLIC_BUCKET", "public")
    monkeypatch.setattr(settings, "B2_PUBLIC_PREVIEW_ENABLED", True)
    monkeypatch.setattr(route.StorageFactory, "get_storage", MissingStorage)
    app = FastAPI()
    app.include_router(object_uploads.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.get("/api/v1/oss-files/public/avatar/missing.png")
    assert result.status_code == 404
    assert result.json()["code"] == 404


@pytest.mark.asyncio
async def test_b4_route_uses_authenticated_id_and_write_gate(monkeypatch):
    app = FastAPI()
    app.dependency_overrides[require_login] = lambda: CurrentUser(7, "USER")
    app.include_router(dataset_routes.router)
    called = []

    async def list_datasets(user_id, page, page_size):
        called.append((user_id, page, page_size))
        return {"items": [], "total": 0, "page": page, "pageSize": page_size, "totalPages": 0}

    monkeypatch.setattr(dataset_routes.datasets, "list_datasets", list_datasets)
    monkeypatch.setattr(settings, "B4_DATASET_WRITES_ENABLED", False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        listed = await client.get("/api/v1/datasets?page=2&pageSize=3&userId=99")
        blocked = await client.post(
            "/api/v1/datasets",
            json={
                "name": "probe",
                "dense_embedding_config_id": 1,
                "sparse_embedding_config_id": 2,
            },
        )
    assert listed.status_code == 200
    assert called == [(7, 2, 3)]
    assert blocked.status_code == 503


@pytest.mark.asyncio
async def test_b5_internal_download_requires_service_token_and_returns_bytes(monkeypatch):
    app = FastAPI()
    app.include_router(internal_document_files.router)
    monkeypatch.setattr(settings, "B5_INTERNAL_FILE_SERVICE_TOKEN", "service-only")

    class Query:
        def mappings(self):
            return self

        def one_or_none(self):
            return {
                "original_filename": "report.pdf",
                "content_type": "application/pdf",
                "bucket_name": "raw",
                "object_key": "7/5/report.pdf",
            }

    class DB:
        async def execute(self, *_args, **_kwargs):
            return Query()

    @asynccontextmanager
    async def context():
        yield DB()

    class Storage:
        def download_to_path(self, bucket, key, path):
            assert (bucket, key) == ("raw", "7/5/report.pdf")
            path.write_bytes(b"%PDF-probe")

    monkeypatch.setattr(internal_document_files, "get_db_context", context)
    monkeypatch.setattr(internal_document_files.StorageFactory, "get_storage", lambda: Storage())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.get("/api/v1/internal/files/3/content")
        user_jwt = await client.get(
            "/api/v1/internal/files/3/content", headers={"Authorization": "Bearer user-jwt"}
        )
        valid = await client.get(
            "/api/v1/internal/files/3/content", headers={"Authorization": "Bearer service-only"}
        )
    assert missing.status_code == user_jwt.status_code == 401
    assert valid.status_code == 200
    assert valid.content == b"%PDF-probe"
    assert valid.headers["content-type"] == "application/pdf"
    assert "report.pdf" in valid.headers["content-disposition"]
