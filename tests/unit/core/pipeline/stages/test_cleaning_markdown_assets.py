from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.dataset_config import EnhancementConfig
from src.core.pipeline.parse_task.stages.services import StageServices


def _payload():
    return SimpleNamespace(
        task_id="task-1",
        user_id=1,
        dataset_id=2,
        original_file_id=3,
        source_bucket="tolink-rag-raw",
        source_object_key=(
            "markdown-assets/v1/user-1/dataset-2/file-3/source/normalized.md"
        ),
        source_filename="guide.md",
    )


def _services(loader):
    return StageServices(
        storage=MagicMock(),
        source_io=MagicMock(),
        chunk_repository=MagicMock(),
        raw_asset_loader=loader,
    )


@pytest.mark.asyncio
async def test_disabled_image_enhancement_does_not_scan_or_download():
    loader = MagicMock()
    markdown = "![a](tolink-raw://raw/never-downloaded.png)"

    result = await _services(loader).enhance_markdown_raw_images(
        markdown,
        _payload(),
        EnhancementConfig(enable_image_enhancement=False),
    )

    assert result == markdown
    loader.load_batch.assert_not_called()


@pytest.mark.asyncio
async def test_successful_raw_image_is_described(monkeypatch):
    uri = (
        "tolink-raw://raw/markdown-assets/v1/user-1/dataset-2/file-3/images/"
        f"image-{'a' * 64}.png"
    )
    loader = MagicMock()
    loader.load_batch = AsyncMock(return_value={uri: (b"image", "image/png")})
    vision = MagicMock()
    vision.adescribe_images = AsyncMock(return_value={uri: "架构示意图"})
    monkeypatch.setattr(
        "src.core.pipeline.parse_task.stages.services.abuild_vision_client",
        AsyncMock(return_value=vision),
    )

    result = await _services(loader).enhance_markdown_raw_images(
        f"![架构]({uri})",
        _payload(),
        EnhancementConfig(enable_table_enhancement=False, enable_image_enhancement=True),
    )

    loader.load_batch.assert_awaited_once_with([uri], _payload())
    assert "架构示意图" in result
    assert uri in result


@pytest.mark.asyncio
async def test_failed_raw_image_load_keeps_original_markdown(monkeypatch):
    uri = (
        "tolink-raw://raw/markdown-assets/v1/user-1/dataset-2/file-3/images/"
        f"image-{'b' * 64}.png"
    )
    loader = MagicMock()
    loader.load_batch = AsyncMock(return_value={})
    build_vision = AsyncMock()
    monkeypatch.setattr(
        "src.core.pipeline.parse_task.stages.services.abuild_vision_client", build_vision
    )

    result = await _services(loader).enhance_markdown_raw_images(
        f"![架构]({uri})",
        _payload(),
        EnhancementConfig(enable_table_enhancement=False, enable_image_enhancement=True),
    )

    assert uri in result
    build_vision.assert_not_awaited()
