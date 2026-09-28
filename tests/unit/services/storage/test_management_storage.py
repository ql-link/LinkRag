from pathlib import Path

import pytest

from src.services.storage.minio_storage import MinioStorage


class FakeS3:
    def __init__(self):
        self.uploaded = None
        self.deleted = None

    def upload_fileobj(self, stream, bucket, key, ExtraArgs):
        assert not isinstance(stream, bytes)
        self.uploaded = (bucket, key, stream.read(), ExtraArgs)

    def delete_object(self, **kwargs):
        self.deleted = kwargs


def test_path_upload_and_exact_delete(tmp_path: Path):
    source = tmp_path / "avatar.png"
    source.write_bytes(b"image-data")
    storage = MinioStorage.__new__(MinioStorage)
    storage._client = FakeS3()
    storage.upload_path("tolink-public", "avatar/7.png", source, "image/png")
    assert storage._client.uploaded == (
        "tolink-public",
        "avatar/7.png",
        b"image-data",
        {"ContentType": "image/png"},
    )
    storage.remove_object("tolink-public", "avatar/7.png")
    assert storage._client.deleted == {"Bucket": "tolink-public", "Key": "avatar/7.png"}
    with pytest.raises(ValueError):
        storage.remove_object("tolink-public", "")


def test_public_url_never_falls_back_to_private_endpoint(monkeypatch):
    from src.services.storage import minio_storage

    storage = MinioStorage.__new__(MinioStorage)
    monkeypatch.setattr(minio_storage.settings, "MINIO_PUBLIC_BASE_URL", None)
    with pytest.raises(ValueError):
        storage.build_public_url("tolink-public", "a.png")
    monkeypatch.setattr(
        minio_storage.settings, "MINIO_PUBLIC_BASE_URL", "https://cdn.example.test"
    )
    assert storage.build_public_url("tolink-public", "头像/a b.png") == (
        "https://cdn.example.test/%E5%A4%B4%E5%83%8F/a%20b.png"
    )
    with pytest.raises(ValueError):
        storage.build_public_url("tolink-rag-docs", "private.png")
    with pytest.raises(ValueError):
        storage.build_public_url("tolink-public", "../private.png")


def test_unsupported_storage_provider_rejected_at_startup_check(monkeypatch):
    from src.services.storage import factory

    monkeypatch.setattr(factory.settings, "STORAGE_TYPE", "oss")
    with pytest.raises(NotImplementedError):
        factory.StorageFactory.validate_provider()
