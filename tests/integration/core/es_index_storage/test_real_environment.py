from __future__ import annotations

import os
from contextlib import suppress
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.config import settings
from src.core.es_index_storage.client import close_async_es_client, get_async_es_client
from src.core.es_index_storage.pipeline import EsIndexingPipeline
from src.core.es_index_storage.smoke import run_es_index_smoke
from src.core.preprocessor.models import ChunkWithTokens, FileIndexMeta, FilePostIndexPlan


def _enabled_real_es_tests() -> bool:
    return os.getenv("TOLINK_RUN_REAL_ES_INDEX_TESTS", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


pytestmark = [
    pytest.mark.real_env,
    pytest.mark.skipif(
        not _enabled_real_es_tests(),
        reason="Set TOLINK_RUN_REAL_ES_INDEX_TESTS=1 to run real Elasticsearch tests.",
    ),
]


@pytest.mark.asyncio
async def test_should_index_and_locate_chunk_when_real_es_enabled():
    index_name = f"test_es_index_{uuid4().hex[:12]}"
    chunk_id = f"chunk-{uuid4().hex[:8]}"
    plan = FilePostIndexPlan(
        file_meta=FileIndexMeta(user_id=20, dataset_id=30, doc_id=10, task_id="t-smoke"),
        chunks_with_tokens=[
            ChunkWithTokens(
                chunk_id=chunk_id,
                chunk_index=0,
                coarse_tokens="合同 付款 违约责任",
                fine_tokens="合同 付款 违约 责任",
            )
        ],
    )
    pipeline = EsIndexingPipeline(index_name=index_name, chunk_repository=AsyncMock())
    client = await get_async_es_client(settings)

    try:
        result = await pipeline.write_es_index(plan, db=AsyncMock())
        assert result.is_success is True

        await client.indices.refresh(index=index_name)
        located = await run_es_index_smoke(
            client=client,
            index_name=index_name,
            dataset_id=30,
            token="付款",
            expected_chunk_id=chunk_id,
        )
        assert located is True
    finally:
        with suppress(Exception):
            await client.indices.delete(index=index_name)
        await close_async_es_client()
