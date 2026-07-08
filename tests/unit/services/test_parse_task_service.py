import pytest

from src.core.parse_task_service import ParseTaskService


class _FakeVisionClient:
    def __init__(self) -> None:
        self.seen_urls: list[str] = []

    async def adescribe_images(
        self,
        image_urls,
        source_file=None,
        image_bytes_by_url=None,
    ):
        self.seen_urls = list(image_urls)
        return {url: "图片展示了系统模块之间的数据流。" for url in image_urls}


@pytest.mark.asyncio
async def test_enhance_existing_markdown_reads_internal_asset_url_and_strips_token(monkeypatch):
    vision_client = _FakeVisionClient()
    monkeypatch.setattr(
        "src.core.markdown_parser.orchestrator.build_default_vision_client",
        lambda: vision_client,
    )
    monkeypatch.setattr(
        "src.config.settings.MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT",
        True,
    )

    image_url = (
        "http://tolink-service:8080/api/v1/internal/files/101/assets"
        "?path=images%2Farch.png&token=internal-token"
    )
    result = await ParseTaskService.aenhance_existing_markdown(
        f"# 架构\n\n![架构图]({image_url})\n",
        source_file="arch.md",
        metadata={"format": "markdown", "passthrough": True},
    )

    markdown = result["markdown"]
    assert vision_client.seen_urls == [image_url]
    assert "[视觉描述|src=" in markdown
    assert "图片展示了系统模块之间的数据流。" in markdown
    assert "token=internal-token" not in markdown
    assert (
        "http://tolink-service:8080/api/v1/internal/files/101/assets?path=images%2Farch.png"
        in markdown
    )
    assert result["metadata"]["markdown_internal_asset_tokens_stripped"] == 2
    assert result["metadata"]["markdown_enhanced"] is True
    assert isinstance(result["time_cost_ms"], int)
