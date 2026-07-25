from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.core.pipeline.parse_task.raw_markdown_assets import RawMarkdownAssetLoader


def _payload(**changes):
    values = {
        "task_id": "task-1",
        "user_id": 1,
        "dataset_id": 2,
        "original_file_id": 3,
        "source_bucket": "tolink-rag-raw",
        "source_object_key": (
            "markdown-assets/v1/user-1/dataset-2/file-3/source/normalized.md"
        ),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _uri(extension: str = "png") -> str:
    return (
        "tolink-raw://raw/markdown-assets/v1/user-1/dataset-2/file-3/images/"
        f"image-{'a' * 64}.{extension}"
    )


@pytest.mark.parametrize(
    "uri,payload",
    [
        (_uri().replace("tolink-raw", "https", 1), _payload()),
        (_uri().replace("//raw/", "//evil/", 1), _payload()),
        (_uri().replace("user-1", "user-9", 1), _payload()),
        (_uri().replace("images/", "images/%2e%2e/", 1), _payload()),
        (_uri() + "?token=secret", _payload()),
        (_uri(), _payload(source_bucket="other")),
    ],
)
@pytest.mark.asyncio
async def test_scope_violation_never_calls_storage(tmp_path, uri, payload):
    storage = MagicMock()
    loader = RawMarkdownAssetLoader(storage, temp_dir=tmp_path)

    assert await loader.load_one(uri, payload) is None
    storage.download_to_path.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extension,expected_mime",
    [
        ("jpg", "image/jpeg"),
        ("png", "image/png"),
        ("gif", "image/gif"),
        ("webp", "image/webp"),
    ],
)
async def test_loads_direct_vision_formats_without_conversion(
    tmp_path, extension, expected_mime
):
    content = b"raw-image"
    storage = MagicMock()
    storage.download_to_path.side_effect = (
        lambda bucket, object_key, dst: dst.write_bytes(content)
    )
    loader = RawMarkdownAssetLoader(storage, max_bytes=1024, temp_dir=tmp_path)

    loaded = await loader.load_one(_uri(extension), _payload())

    assert loaded == (content, expected_mime)
    storage.download_to_path.assert_called_once()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_oversized_image_is_not_read_and_is_cleaned(tmp_path):
    storage = MagicMock()
    storage.download_to_path.side_effect = lambda bucket, object_key, dst: dst.write_bytes(b"12345")
    loader = RawMarkdownAssetLoader(storage, max_bytes=4, temp_dir=tmp_path)

    assert await loader.load_one(_uri(), _payload()) is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("extension", ["bmp", "tiff"])
async def test_bitmap_formats_are_decoded_once_and_sent_as_png(
    tmp_path, monkeypatch, extension
):
    storage = MagicMock()
    storage.download_to_path.side_effect = lambda bucket, object_key, dst: dst.write_bytes(b"TIFF")
    loader = RawMarkdownAssetLoader(storage, temp_dir=tmp_path)
    converted = (b"PNG", "image/png")
    convert = MagicMock(return_value=converted)
    monkeypatch.setattr(loader, "_convert_to_png", convert)

    assert await loader.load_one(_uri(extension), _payload()) == converted
    convert.assert_called_once_with(b"TIFF")
    assert list(tmp_path.iterdir()) == []
