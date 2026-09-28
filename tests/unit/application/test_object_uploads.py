from unittest.mock import Mock

import pytest

from src.api.management_http import BusinessError
from src.application.object_uploads import RULES, generate_object_key, upload_object, validate_upload


@pytest.mark.parametrize(
    ("kind", "name", "place", "limit"),
    [
        ("avatar", "a.PNG", "PUBLIC", 5),
        ("providerIcon", "a.webp", "PUBLIC", 5),
        ("chatImage", "a.jpeg", "PUBLIC", 5),
        ("document", "a.txt", "RAW", 20),
        ("cert", "a.pem", "PRIVATE", 5),
        ("feedback", "a.docx", "PUBLIC", 10),
    ],
)
def test_java_rule_matrix(kind, name, place, limit):
    rule, suffix = validate_upload(kind, name, b"x")
    assert rule.place == place
    assert rule.max_bytes == limit * 1024 * 1024
    assert suffix == name.rsplit(".", 1)[1].lower()
    assert len(RULES) == 6


def test_validation_order_and_size_boundary():
    with pytest.raises(BusinessError, match="请选择要上传的文件"):
        validate_upload("unknown", "a.exe", b"")
    with pytest.raises(BusinessError, match="上传业务类型不支持"):
        validate_upload("unknown", "a.exe", b"x")
    with pytest.raises(BusinessError, match="上传文件格式不支持"):
        validate_upload("avatar", "a.exe", b"x")
    validate_upload("avatar", "a.png", b"x" * (5 * 1024 * 1024))
    with pytest.raises(BusinessError, match="上传大小请限制在 5M 以内"):
        validate_upload("avatar", "a.png", b"x" * (5 * 1024 * 1024 + 1))
    for suffix in ("markdown", "html", "htm"):
        with pytest.raises(BusinessError, match="上传文件格式不支持"):
            validate_upload("document", f"a.{suffix}", b"x")


def test_java_key_shape():
    assert generate_object_key("avatar", "png").startswith("avatar/")
    assert generate_object_key("feedback", "txt").count("/") == 3
    assert generate_object_key("cert", "").startswith("cert/")


@pytest.mark.asyncio
async def test_public_returns_url_private_and_raw_return_key(monkeypatch):
    import src.application.object_uploads as module

    monkeypatch.setattr(module.settings, "MINIO_PUBLIC_BUCKET", "public")
    monkeypatch.setattr(module.settings, "MINIO_PRIVATE_BUCKET", "private")
    monkeypatch.setattr(module.settings, "MINIO_RAW_BUCKET", "raw")
    storage = Mock()
    storage.build_public_url.side_effect = lambda bucket, key: f"https://cdn/{key}"
    public = await upload_object("avatar", "a.png", b"data", storage=storage)
    assert public.result == f"https://cdn/{public.key}"
    private = await upload_object("cert", "a.pem", b"data", storage=storage)
    raw = await upload_object("document", "a.pdf", b"data", storage=storage)
    assert (private.bucket, private.result) == ("private", private.key)
    assert (raw.bucket, raw.result) == ("raw", raw.key)
    storage.build_public_url.assert_called_once()
