from unittest.mock import AsyncMock, MagicMock

from src.core.es_index_storage import EsIndexingPipeline
from src.core.preprocessor.models import ChunkWithTokens, FileIndexMeta, FilePostIndexPlan


def build_plan(count: int = 2) -> FilePostIndexPlan:
    chunks = [
        ChunkWithTokens(
            chunk_id=f"c-{i}",
            chunk_index=i,
            coarse_tokens="合同 付款 违约责任",
            fine_tokens="合同 付款 违约 责任",
        )
        for i in range(count)
    ]
    return FilePostIndexPlan(
        file_meta=FileIndexMeta(user_id=20, dataset_id=30, doc_id=10, task_id="t-001"),
        chunks_with_tokens=chunks,
    )


def bulk_response(statuses: list[int]) -> dict:
    items = []
    for status in statuses:
        if status in (200, 201):
            items.append({"index": {"status": status}})
        else:
            items.append({"index": {"status": status, "error": {"type": "x", "reason": "boom"}}})
    return {"items": items}


def build_client(*, index_exists: bool = True) -> MagicMock:
    client = MagicMock()
    client.indices.exists = AsyncMock(return_value=index_exists)
    client.indices.create = AsyncMock()
    client.bulk = AsyncMock()
    return client


def build_pipeline(client: MagicMock, repo: AsyncMock | None = None):
    repo = repo or AsyncMock()
    pipeline = EsIndexingPipeline(
        client_factory=lambda: client,
        index_name="idx",
        chunk_repository=repo,
    )
    return pipeline, repo


class TestEsIndexingPipeline:
    def test_init_should_not_resolve_client(self):
        factory = MagicMock()
        EsIndexingPipeline(client_factory=factory, index_name="idx", chunk_repository=AsyncMock())

        factory.assert_not_called()

    async def test_should_return_empty_result_for_empty_plan(self):
        client = build_client()
        pipeline, repo = build_pipeline(client)

        result = await pipeline.write_es_index(build_plan(0), db=AsyncMock())

        assert result.total_items == 0
        assert result.is_success is True
        client.bulk.assert_not_awaited()
        repo.mark_es_success.assert_not_awaited()

    async def test_should_index_all_chunks_and_mark_success(self):
        client = build_client()
        client.bulk.return_value = bulk_response([201, 201])
        pipeline, repo = build_pipeline(client)
        db = AsyncMock()

        result = await pipeline.write_es_index(build_plan(2), db=db)

        assert result.is_success is True
        assert result.total_items == 2
        assert result.indexed_items == 2
        assert result.failed_item_ids == []
        repo.mark_es_success.assert_awaited_once_with(db, ["c-0", "c-1"])
        db.commit.assert_awaited()

    async def test_should_mark_failed_chunks_on_partial_bulk_failure(self):
        client = build_client()
        client.bulk.return_value = bulk_response([201, 400])
        pipeline, repo = build_pipeline(client)
        db = AsyncMock()

        result = await pipeline.write_es_index(build_plan(2), db=db)

        assert result.is_success is False
        assert result.indexed_items == 1
        assert result.failed_item_ids == ["c-1"]
        assert result.failure_reason.startswith("ES_INDEXING_FAILED:")
        repo.mark_es_success.assert_awaited_once_with(db, ["c-0"])
        repo.mark_es_failed.assert_awaited_once()
        assert repo.mark_es_failed.await_args.args[1] == ["c-1"]

    async def test_should_fail_file_level_without_marking_chunks_when_ensure_index_fails(self):
        # ensure_index 失败属文件级基础设施故障：不标任何 chunk，
        # failed_item_ids 留空，failure_reason 以 ensure_index: 前缀，is_success False。
        client = build_client()
        client.indices.exists = AsyncMock(side_effect=RuntimeError("es down"))
        pipeline, repo = build_pipeline(client)
        db = AsyncMock()

        result = await pipeline.write_es_index(build_plan(2), db=db)

        assert result.is_success is False
        assert result.failed_item_ids == []
        assert result.failure_reason.startswith("ensure_index:")
        repo.mark_es_failed.assert_not_awaited()
        client.bulk.assert_not_awaited()

    async def test_should_mark_validation_failures_before_bulk(self):
        client = build_client()
        client.bulk.return_value = bulk_response([201])
        pipeline, repo = build_pipeline(client)
        plan = FilePostIndexPlan(
            file_meta=FileIndexMeta(user_id=20, dataset_id=30, doc_id=10, task_id="t-001"),
            chunks_with_tokens=[
                ChunkWithTokens(chunk_id="c-0", chunk_index=0, coarse_tokens="ok", fine_tokens="ok"),
                ChunkWithTokens(chunk_id="c-1", chunk_index=1, coarse_tokens="  ", fine_tokens="ok"),
            ],
        )

        result = await pipeline.write_es_index(plan, db=AsyncMock())

        assert result.total_items == 2
        assert result.indexed_items == 1
        assert result.failed_item_ids == ["c-1"]
        assert repo.mark_es_failed.await_args.args[1] == ["c-1"]

    async def test_should_commit_each_batch_independently(self, monkeypatch):
        from src.config import settings

        monkeypatch.setattr(settings, "ES_MAX_TOKEN_BATCH_CHUNKS", 1)
        client = build_client()
        client.bulk = AsyncMock(side_effect=[bulk_response([201]), ConnectionError("es down")])
        pipeline, repo = build_pipeline(client)
        db = AsyncMock()

        result = await pipeline.write_es_index(build_plan(2), db=db)

        # 第一批成功并 commit，第二批 bulk 异常但前一批状态已落库。
        assert result.indexed_items == 1
        assert result.failed_item_ids == ["c-1"]
        assert db.commit.await_count == 2
        repo.mark_es_success.assert_awaited_once_with(db, ["c-0"])
