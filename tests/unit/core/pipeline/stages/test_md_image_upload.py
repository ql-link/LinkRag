# -*- coding: utf-8 -*-
"""LINK-215：MD passthrough 路径下 base64 图片提取上传逻辑。"""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest

from src.core.pipeline.parse_task.stages.services import _upload_base64_images_sync


def _make_storage(fail: bool = False) -> MagicMock:
    storage = MagicMock()
    if fail:
        storage.upload_bytes.side_effect = RuntimeError("upload error")
    else:
        storage.build_object_url.side_effect = lambda bucket, key: f"http://minio/{bucket}/{key}"
    return storage


# 1x1 PNG（最小合法 PNG，用于测试）
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)
_TINY_PNG_B64 = base64.b64encode(_TINY_PNG).decode()


def test_no_images_returns_unchanged():
    md = "# Hello\n\nSome text without images."
    storage = _make_storage()
    result = _upload_base64_images_sync(md, storage, "bucket", "prefix")
    assert result == md
    storage.upload_bytes.assert_not_called()


def test_base64_png_replaced_with_url():
    md = f"![alt text](data:image/png;base64,{_TINY_PNG_B64})"
    storage = _make_storage()
    result = _upload_base64_images_sync(md, storage, "docs", "img-prefix")

    assert "data:image/png;base64," not in result
    assert result.startswith("![alt text](http://minio/docs/")
    assert result.endswith(".png)")
    storage.upload_bytes.assert_called_once()
    call_kwargs = storage.upload_bytes.call_args
    assert call_kwargs.kwargs["bucket"] == "docs"
    assert call_kwargs.kwargs["object_key"].startswith("img-prefix/")
    assert call_kwargs.kwargs["object_key"].endswith(".png")
    assert call_kwargs.kwargs["content_type"] == "image/png"


def test_multiple_images_all_replaced():
    jpg_bytes = b"JFIF_fake_jpg_bytes"
    jpg_b64 = base64.b64encode(jpg_bytes).decode()
    md = (
        f"![img1](data:image/png;base64,{_TINY_PNG_B64})\n"
        f"![img2](data:image/jpeg;base64,{jpg_b64})"
    )
    storage = _make_storage()
    result = _upload_base64_images_sync(md, storage, "docs", "prefix")

    assert "data:image/png;base64," not in result
    assert "data:image/jpeg;base64," not in result
    assert storage.upload_bytes.call_count == 2
    # jpeg → .jpg 扩展名
    keys = [c.kwargs["object_key"] for c in storage.upload_bytes.call_args_list]
    exts = {k.rsplit(".", 1)[-1] for k in keys}
    assert exts == {"png", "jpg"}


def test_upload_failure_keeps_original(capsys):
    """单张图片上传失败应保留原始 base64，不阻断整篇。"""
    md = f"![img](data:image/png;base64,{_TINY_PNG_B64})"
    storage = _make_storage(fail=True)
    result = _upload_base64_images_sync(md, storage, "docs", "prefix")

    assert result == md  # 原样保留


def test_prefix_strip_slash():
    """image_prefix 两端斜杠应被 strip，生成规范对象路径。"""
    md = f"![x](data:image/png;base64,{_TINY_PNG_B64})"
    storage = _make_storage()
    _upload_base64_images_sync(md, storage, "docs", "/prefix/sub/")

    call_key = storage.upload_bytes.call_args.kwargs["object_key"]
    assert not call_key.startswith("/")
    assert call_key.startswith("prefix/sub/")
