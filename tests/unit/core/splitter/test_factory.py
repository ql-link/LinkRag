"""Unit tests for splitter factory."""

from unittest.mock import MagicMock

import pytest

from src.core.llm.interfaces import CapabilityType
from src.core.splitter.factory import LazyEmbeddingClient


class TestLazyEmbeddingClient:
    """LazyEmbeddingClient 应延迟真实客户端构造，并对 EMBEDDING 能力直接放行。"""

    def test_embedding_capability_does_not_trigger_real_client(self) -> None:
        real_factory = MagicMock(side_effect=AssertionError("must not build until needed"))
        client = LazyEmbeddingClient(real_factory)

        assert client.has_capability(CapabilityType.EMBEDDING) is True
        real_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_embed_triggers_real_client_lazily(self) -> None:
        real_client = MagicMock()

        async def fake_embed(texts, model=None, **kwargs):
            return ["vec"]

        real_client.embed = fake_embed
        real_factory = MagicMock(return_value=real_client)

        client = LazyEmbeddingClient(real_factory)
        # First call constructs the real client
        result = await client.embed("alpha")
        assert result == ["vec"]
        real_factory.assert_called_once()

        # Second call reuses the cached real client
        await client.embed("beta")
        real_factory.assert_called_once()

    @pytest.mark.asyncio
    async def test_embed_propagates_real_client_construction_error(self) -> None:
        real_factory = MagicMock(side_effect=RuntimeError("missing embedding config"))
        client = LazyEmbeddingClient(real_factory)

        with pytest.raises(RuntimeError, match="missing embedding config"):
            await client.embed("alpha")
