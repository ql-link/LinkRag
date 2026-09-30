from src.application import object_uploads
from src.application.object_uploads import public_object_url


class _Storage:
    def build_public_url(self, bucket, key):
        return f"https://cdn.example/{key}"


class _Unconfigured:
    def build_public_url(self, bucket, key):
        raise ValueError("MINIO_PUBLIC_BASE_URL 未配置")


def test_rebuilds_url_from_object_key(monkeypatch):
    monkeypatch.setattr(object_uploads.StorageFactory, "get_storage", lambda: _Storage())
    assert public_object_url("providerIcon/aliyun.svg", "http://old-host/x.svg") == "https://cdn.example/providerIcon/aliyun.svg"


def test_falls_back_to_stored_url(monkeypatch):
    monkeypatch.setattr(object_uploads.StorageFactory, "get_storage", lambda: _Unconfigured())
    assert public_object_url("providerIcon/a.svg", "http://old/a.svg") == "http://old/a.svg"
    assert public_object_url(None, "http://old/a.svg") == "http://old/a.svg"
