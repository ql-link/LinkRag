from unittest.mock import AsyncMock, MagicMock

from src.core.es_index_storage import EsIndexingPipeline
from src.core.mq.messages import ParseTaskMessage
from src.core.splitter.models import Chunk


def build_payload():
    return ParseTaskMessage.build(
        task_id="t-001",
        original_file_id=1,
        document_parse_task_id=10,
        user_id=20,
        dataset_id=30,
        file_type="pdf",
        source_bucket="source-bucket",
        source_object_key="uploads/test.pdf",
        source_filename="test.pdf",
        md_bucket="markdown-bucket",
        md_object_key="parsed/t-001.md",
    ).get_payload()


class TestEsIndexingPipeline:
    async def test_index_for_parse_task_should_return_success_when_all_chunks_indexed(self):
        client = MagicMock()
        client.indices.exists = AsyncMock(return_value=True)
        client.index = AsyncMock()
        pipeline = EsIndexingPipeline(client=client, index_name="idx")

        result = await pipeline.index_for_parse_task(
            payload=build_payload(),
            chunks=[Chunk(content="alpha", start_line=1, end_line=1), Chunk(content="beta", start_line=2, end_line=2)],
        )

        assert result.is_success is True
        assert result.total_items == 2
        assert result.indexed_items == 2
        assert result.failed_item_ids == []
        assert client.index.await_count == 2

    async def test_index_for_parse_task_should_return_failed_summary_when_any_chunk_fails(self):
        client = MagicMock()
        client.indices.exists = AsyncMock(return_value=True)
        client.index = AsyncMock(side_effect=[None, RuntimeError("es down")])
        pipeline = EsIndexingPipeline(client=client, index_name="idx")

        result = await pipeline.index_for_parse_task(
            payload=build_payload(),
            chunks=[Chunk(content="alpha", start_line=1, end_line=1), Chunk(content="beta", start_line=2, end_line=2)],
        )

        assert result.is_success is False
        assert result.total_items == 2
        assert result.indexed_items == 1
        assert result.failed_item_ids == ["t-001-1"]
        assert result.failure_reason == "ES indexing failed"
