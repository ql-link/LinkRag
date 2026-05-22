import asyncio
import base64
from unittest.mock import patch

import pytest

from src.config import settings
from src.core.llm.base_provider import BaseProvider
from src.core.llm.interfaces import CapabilityType
from src.core.llm.response import GenerateResult, StreamChunk, UsageInfo
from src.core.markdown_parser.provider_clients import ProviderVisionClient


class TrackingVisionProvider(BaseProvider):
    def __init__(
        self,
        *,
        delay_seconds: float = 0.01,
        fail_bytes: set[bytes] | None = None,
        empty_bytes: set[bytes] | None = None,
    ) -> None:
        super().__init__(provider_type="fake-vision", provider_name="fake-vision", api_key="")
        self._capabilities = {CapabilityType.VISION}
        self.delay_seconds = delay_seconds
        self.fail_bytes = fail_bytes or set()
        self.empty_bytes = empty_bytes or set()
        self.active = 0
        self.peak_active = 0
        self.seen_image_bytes: list[bytes] = []

    async def generate(self, prompt, system_prompt=None, temperature=0.7, max_tokens=None, **kwargs):
        raise NotImplementedError

    async def stream(self, prompt, system_prompt=None, temperature=0.7, max_tokens=None, **kwargs):
        yield StreamChunk(delta="", content="", is_end=True)

    async def analyze_image(self, image_base64, prompt, **kwargs):
        image_bytes = base64.b64decode(image_base64)
        self.seen_image_bytes.append(image_bytes)
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        try:
            await asyncio.sleep(self.delay_seconds)
            if image_bytes in self.fail_bytes:
                raise RuntimeError("vision call failed")
            content = "" if image_bytes in self.empty_bytes else f"description:{image_bytes.decode('utf-8')}"
            return GenerateResult(
                content=content,
                model="fake-vision-model",
                usage=UsageInfo(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                provider_type=self.provider_type,
                latency_ms=1,
            )
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_provider_vision_client_defaults_to_configured_concurrency(monkeypatch):
    monkeypatch.setattr(settings, "MARKDOWN_PARSER_VISION_CONCURRENCY", 24)
    provider = TrackingVisionProvider()
    client = ProviderVisionClient(provider=provider, max_concurrency=None)
    images = {
        f"memory://image-{index}.png": (f"image-{index}".encode("utf-8"), "image/png")
        for index in range(30)
    }

    result = await client.adescribe_images(list(images), image_bytes_by_url=images)

    assert client._max_concurrency == 24
    assert len(result) == 30
    assert provider.peak_active <= 24


@pytest.mark.asyncio
async def test_provider_vision_client_respects_injected_concurrency():
    provider = TrackingVisionProvider(delay_seconds=0.02)
    client = ProviderVisionClient(provider=provider, max_concurrency=3)
    images = {
        f"memory://image-{index}.png": (f"image-{index}".encode("utf-8"), "image/png")
        for index in range(10)
    }

    result = await client.adescribe_images(list(images), image_bytes_by_url=images)

    assert len(result) == 10
    assert provider.peak_active <= 3
    assert provider.peak_active > 1


def test_provider_vision_client_normalizes_invalid_concurrency():
    provider = TrackingVisionProvider()

    assert ProviderVisionClient(provider=provider, max_concurrency=0)._max_concurrency == 1
    assert ProviderVisionClient(provider=provider, max_concurrency=-1)._max_concurrency == 1
    assert ProviderVisionClient(provider=provider, max_concurrency="invalid")._max_concurrency == 1


@pytest.mark.asyncio
async def test_provider_vision_client_isolates_per_image_failures_and_empty_results():
    provider = TrackingVisionProvider(
        fail_bytes={b"bad-image"},
        empty_bytes={b"empty-image"},
    )
    client = ProviderVisionClient(provider=provider, max_concurrency=3)
    images = {
        "memory://ok.png": (b"ok-image", "image/png"),
        "memory://bad.png": (b"bad-image", "image/png"),
        "memory://empty.png": (b"empty-image", "image/png"),
    }

    result = await client.adescribe_images(list(images), image_bytes_by_url=images)

    assert result == {"memory://ok.png": "description:ok-image"}


@pytest.mark.asyncio
async def test_provider_vision_client_prefers_memory_bytes_without_reencoding():
    provider = TrackingVisionProvider()
    client = ProviderVisionClient(provider=provider, max_concurrency=2)
    image_url = "http://minio/rag-md/image/doc/picture.png"
    original_bytes = b"original-image-bytes"

    with patch("src.core.markdown_parser.provider_clients._load_image_bytes") as mock_load:
        result = await client.adescribe_images(
            [image_url],
            source_file="docs/example.md",
            image_bytes_by_url={image_url: (original_bytes, "image/png")},
        )

    assert result[image_url] == "description:original-image-bytes"
    assert provider.seen_image_bytes == [original_bytes]
    mock_load.assert_not_called()


@pytest.mark.asyncio
async def test_provider_vision_client_loads_non_memory_images_in_worker_thread():
    provider = TrackingVisionProvider()
    client = ProviderVisionClient(provider=provider, max_concurrency=2)
    image_url = "http://minio/rag-md/image/doc/picture.png"

    with patch(
        "src.core.markdown_parser.provider_clients._load_image_bytes",
        return_value=(b"url-image-bytes", "image/png"),
    ) as mock_load:
        result = await client.adescribe_images([image_url], source_file="docs/example.md")

    assert result[image_url] == "description:url-image-bytes"
    assert provider.seen_image_bytes == [b"url-image-bytes"]
    mock_load.assert_called_once_with(image_url, "docs/example.md")
