from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.core.es_index_storage.client as client_module
from src.core.es_index_storage.client import close_async_es_client, get_async_es_client


class _FakeSettings:
    ES_HOST = "http://localhost:9200"
    ES_USER = None
    ES_PASSWORD = None
    ES_BULK_REQUEST_TIMEOUT_SECONDS = 30


@pytest.fixture(autouse=True)
def _reset_client():
    client_module._client = None
    yield
    client_module._client = None


class TestEsClient:
    async def test_should_initialize_client_only_once(self):
        with patch.object(client_module, "AsyncElasticsearch") as mock_es:
            mock_es.return_value = MagicMock()

            first = await get_async_es_client(_FakeSettings())
            second = await get_async_es_client(_FakeSettings())

        assert first is second
        assert mock_es.call_count == 1

    async def test_should_reinitialize_after_close(self):
        with patch.object(client_module, "AsyncElasticsearch") as mock_es:
            instance = MagicMock()
            instance.close = AsyncMock()
            mock_es.return_value = instance

            await get_async_es_client(_FakeSettings())
            await close_async_es_client()
            await get_async_es_client(_FakeSettings())

        instance.close.assert_awaited_once()
        assert mock_es.call_count == 2

    async def test_should_pass_basic_auth_when_credentials_present(self):
        class _AuthSettings(_FakeSettings):
            ES_USER = "elastic"
            ES_PASSWORD = "secret"

        with patch.object(client_module, "AsyncElasticsearch") as mock_es:
            mock_es.return_value = MagicMock()
            await get_async_es_client(_AuthSettings())

        assert mock_es.call_args.kwargs["basic_auth"] == ("elastic", "secret")
