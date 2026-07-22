from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.core.markdown_parser import ImageDescriber, MarkdownParser


@pytest.mark.asyncio
async def test_image_describer_only_sends_requested_document_urls():
    first = "tolink-raw://raw/first.png"
    second = "tolink-raw://raw/second.png"
    result = MarkdownParser().parse(f"![a]({first})\n\n![b]({second})")
    client = AsyncMock()
    client.adescribe_images.return_value = {second: "第二张图片"}

    enriched = await ImageDescriber(client).aprocess(
        result,
        image_bytes_by_url={second: (b"image", "image/png")},
        target_urls=[second, "tolink-raw://raw/not-in-document.png"],
    )

    client.adescribe_images.assert_awaited_once_with(
        [second],
        None,
        image_bytes_by_url={second: (b"image", "image/png")},
    )
    assert "第二张图片" in enriched.to_markdown()
    assert "first.png: 第二张图片" not in enriched.to_markdown()
