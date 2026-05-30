"""测试 ParseTaskPipeline 的 6 阶段执行顺序。

本测试文件专注于验证：
1. 6 个阶段按正确顺序执行：CLEANING → CHUNKING → VECTORIZING → PRETOKENIZE → ES_INDEXING → SPARSE_VECTORIZING
2. sparse 阶段在 ES 成功后执行
3. sparse 成功才翻转 pipeline_status=SUCCESS
4. sparse 失败时的正确处理
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.es_index_storage.models import EsIndexingResult
from src.core.pipeline.parse_task.pipeline import ParseTaskPipeline, PipelineStatus
from src.core.pipeline.parse_task.post_process.constants import (
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_SUCCESS,
    STAGE_STATUS_FAILED,
    STAGE_STATUS_SUCCESS,
)
from src.core.preprocessor.models import ChunkWithTokens, FileIndexMeta, FilePostIndexPlan
from src.core.splitter.models import Chunk
from src.core.vector_storage.models import ChunkIndexingResult
from tests.unit.core.pipeline.test_parse_task_pipeline import (
    FakeAsyncSessionFactory,
    FakeEsIndexingPipeline,
    FakePostProcessRepository,
    FakePreprocessor,
    build_db,
    build_parse_task,
    build_payload,
)


def make_fake_reload_chunks(count: int = 2):
    """构造 ``_reload_chunks_from_db`` 的 fake：返回 N 条 ORM 行。

    本期 ``_run_chunking`` commit 后 + sparse 阶段开始前都会调 reload；测试用
    fake 屏蔽真实 SQL 反查，让 chunks 透传到 dense / sparse 入口。

    返回的 chunks 状态：``dense=PENDING, sparse=PENDING, es=PENDING``——
    用 OrderTrackingVectorStorage 替身的测试会"假装" dense 处理成功（替身永远
    返回 indexed_chunks=count），但**chunk 本身的 dense_vector_status 仍然是 PENDING**。
    sparse 阶段在第二次 reload 时再调本 fake，会再返回 PENDING——但 sparse 阶段在
    OrderTrackingSparseIndexingPipeline 替身里也是被替换的，不会触发真实的前置断言。
    所以 fake reload 的状态搭配替身使用即可，不必模拟"dense 已 SUCCESS"的真实推进。
    """

    async def fake_reload(payload, db):
        from src.core.chunk_fact_storage.constants import (
            CHUNK_STATUS_PENDING,
            ES_STATUS_PENDING,
            SPARSE_VECTOR_STATUS_PENDING,
        )
        from src.models.chunk_record import ChunkRecordDB

        return [
            ChunkRecordDB(
                id=i + 1,
                chunk_id=f"chunk-{i}",
                doc_id=1,
                set_id=30,
                user_id=20,
                bucket_id=42,
                content="x",
                content_hash="h",
                chunk_type="text",
                start_line=0,
                end_line=0,
                chunk_index=i,
                dense_vector_status=CHUNK_STATUS_PENDING,
                sparse_vector_status=SPARSE_VECTOR_STATUS_PENDING,
                es_status=ES_STATUS_PENDING,
            )
            for i in range(count)
        ]

    return fake_reload


class OrderTrackingSparseIndexingPipeline:
    """追踪调用顺序的 SparseIndexingPipeline 替身。"""

    def __init__(self, *, should_fail: bool = False, order_tracker: list | None = None):
        self.should_fail = should_fail
        # 确保使用传入的列表引用，而不是创建新列表
        if order_tracker is None:
            self.order_tracker = []
        else:
            self.order_tracker = order_tracker
        self.run_called = False

    async def run(self, *, chunks, task_id: str, db):
        self.run_called = True
        self.order_tracker.append("sparse_run")
        if self.should_fail:
            from src.core.sparse_vector.indexing import SparseIndexingError

            raise SparseIndexingError("SPARSE_VECTORIZING_FAILED:test_error")


class OrderTrackingEsIndexingPipeline:
    """追踪调用顺序的 EsIndexingPipeline 替身。"""

    def __init__(self, *, order_tracker: list | None = None):
        if order_tracker is None:
            self.order_tracker = []
        else:
            self.order_tracker = order_tracker

    async def delete_document_index(self, *, user_id, dataset_id, doc_id):
        # ES 文档级全量重建：前置删除发生在写入之前。
        self.order_tracker.append("es_delete")
        return 0

    async def write_es_index(self, plan, *, db):
        self.order_tracker.append("es_write")
        return EsIndexingResult(total_items=2, indexed_items=2)


class OrderTrackingVectorStorage:
    """追踪调用顺序的 VectorStorage 替身。"""

    def __init__(self, *, order_tracker: list | None = None):
        if order_tracker is None:
            self.order_tracker = []
        else:
            self.order_tracker = order_tracker

    async def index_chunks(self, **kwargs):
        self.order_tracker.append("vector_index")
        return ChunkIndexingResult(total_chunks=2, indexed_chunks=2)


class OrderTrackingPreprocessor:
    """追踪调用顺序的 Preprocessor 替身。"""

    def __init__(self, *, order_tracker: list | None = None):
        if order_tracker is None:
            self.order_tracker = []
        else:
            self.order_tracker = order_tracker

    async def build_file_post_index_plan(self, *, doc_id: int, task_id: str):
        self.order_tracker.append("pretokenize")
        return FilePostIndexPlan(
            file_meta=FileIndexMeta(user_id=20, dataset_id=30, doc_id=doc_id, task_id=task_id),
            chunks_with_tokens=[
                ChunkWithTokens(
                    chunk_id="c1",
                    chunk_index=0,
                    coarse_tokens="test",
                    fine_tokens="test",
                ),
                ChunkWithTokens(
                    chunk_id="c2",
                    chunk_index=1,
                    coarse_tokens="test2",
                    fine_tokens="test2",
                ),
            ],
        )


class TestPipelineSixStageOrder:
    """测试 6 阶段执行顺序。"""

    @patch(
        "src.core.pipeline.parse_task.pipeline.ParseTaskService.aprocess",
        new_callable=AsyncMock,
    )
    @patch("src.core.pipeline.parse_task.pipeline.ParseTaskPipeline._chunk_markdown")
    async def test_six_stages_execute_in_correct_order(
        self,
        mock_chunk_markdown,
        mock_aprocess,
        monkeypatch,
        tmp_path,
    ):
        """验证 6 个阶段按正确顺序执行：CLEANING → CHUNKING → VECTORIZING → PRETOKENIZE → ES → SPARSE。"""
        db = build_db(build_parse_task())
        monkeypatch.setattr(
            "src.core.pipeline.parse_task.pipeline.settings.PARSE_TEMP_DIR",
            str(tmp_path),
        )
        order_tracker = []

        storage = MagicMock()
        storage.download_to_path.side_effect = lambda bucket, object_key, dst: dst.write_bytes(
            b"pdf bytes"
        )
        storage.upload_bytes.side_effect = lambda **kwargs: order_tracker.append("cleaning_upload")

        mq_service = MagicMock()
        mq_service.send = AsyncMock()

        # Mock ChunkRepository instance directly
        mock_chunk_repo = AsyncMock()
        mock_chunk_repo.bulk_insert_pending = AsyncMock()

        vector_storage = OrderTrackingVectorStorage(order_tracker=order_tracker)
        preprocessor = OrderTrackingPreprocessor(order_tracker=order_tracker)
        es_pipeline = OrderTrackingEsIndexingPipeline(order_tracker=order_tracker)
        sparse_pipeline = OrderTrackingSparseIndexingPipeline(order_tracker=order_tracker)
        post_repo = FakePostProcessRepository()

        mock_aprocess.return_value = {
            "markdown": "parsed content",
            "parse_result": MagicMock(),
            "metadata": {"pages_or_length": 3},
            "time_cost_ms": 120,
        }
        mock_chunk_markdown.return_value = [
            Chunk(content="alpha", start_line=1, end_line=1),
            Chunk(content="beta", start_line=2, end_line=2),
        ]

        pipeline = ParseTaskPipeline(
            storage=storage,
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
            vector_storage=vector_storage,
            pipeline_repository=post_repo,
            es_indexing_pipeline=es_pipeline,
            preprocessor=preprocessor,
            sparse_indexing_pipeline=sparse_pipeline,
            chunk_repository=mock_chunk_repo,
        )

        # _run_chunking 与 sparse 阶段会调 _reload_chunks_from_db；mock 一下让它返回 2 条 ORM 行
        pipeline._reload_chunks_from_db = make_fake_reload_chunks(count=2)

        payload = build_payload()
        payload.pdf_parser_backend = "opendataloader"

        result = await pipeline.execute(payload)

        # 验证成功
        assert result.status == PipelineStatus.SUCCESS
        assert result.chunk_count == 2

        # 验证阶段顺序：cleaning → chunking(隐式) → vector → pretokenize → es(删除→写入) → sparse
        assert order_tracker == [
            "cleaning_upload",  # CLEANING 阶段
            # CHUNKING 阶段没有显式追踪（在 _persist_chunk_facts 中）
            "vector_index",  # VECTORIZING 阶段
            "pretokenize",  # PRETOKENIZE 阶段
            "es_delete",  # ES_INDEXING：文档级全量重建前置删除
            "es_write",  # ES_INDEXING：全量写入
            "sparse_run",  # SPARSE_VECTORIZING 阶段
        ]

        # 验证 sparse 确实被调用
        assert sparse_pipeline.run_called is True

        # 验证最终状态
        assert post_repo.pipeline.pipeline_status == PIPELINE_STATUS_SUCCESS
        assert post_repo.pipeline.sparse_vectorizing_status == STAGE_STATUS_SUCCESS

    @patch(
        "src.core.pipeline.parse_task.pipeline.ParseTaskService.aprocess",
        new_callable=AsyncMock,
    )
    @patch("src.core.pipeline.parse_task.pipeline.ParseTaskPipeline._chunk_markdown")
    async def test_sparse_failure_marks_pipeline_failed(
        self,
        mock_chunk_markdown,
        mock_aprocess,
        monkeypatch,
        tmp_path,
    ):
        """验证 sparse 失败时正确标记 pipeline 失败。"""
        db = build_db(build_parse_task())
        monkeypatch.setattr(
            "src.core.pipeline.parse_task.pipeline.settings.PARSE_TEMP_DIR",
            str(tmp_path),
        )
        order_tracker = []

        storage = MagicMock()
        storage.download_to_path.side_effect = lambda bucket, object_key, dst: dst.write_bytes(
            b"pdf bytes"
        )
        storage.upload_bytes.side_effect = lambda **kwargs: None

        mq_service = MagicMock()
        mq_service.send = AsyncMock()

        # Mock ChunkRepository instance directly
        mock_chunk_repo = AsyncMock()
        mock_chunk_repo.bulk_insert_pending = AsyncMock()

        vector_storage = OrderTrackingVectorStorage(order_tracker=order_tracker)
        preprocessor = OrderTrackingPreprocessor(order_tracker=order_tracker)
        es_pipeline = OrderTrackingEsIndexingPipeline(order_tracker=order_tracker)
        sparse_pipeline = OrderTrackingSparseIndexingPipeline(
            should_fail=True, order_tracker=order_tracker
        )
        post_repo = FakePostProcessRepository()

        mock_aprocess.return_value = {
            "markdown": "parsed content",
            "parse_result": MagicMock(),
            "metadata": {"pages_or_length": 3},
            "time_cost_ms": 120,
        }
        mock_chunk_markdown.return_value = [
            Chunk(content="alpha", start_line=1, end_line=1),
        ]

        pipeline = ParseTaskPipeline(
            storage=storage,
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
            vector_storage=vector_storage,
            pipeline_repository=post_repo,
            es_indexing_pipeline=es_pipeline,
            preprocessor=preprocessor,
            sparse_indexing_pipeline=sparse_pipeline,
            chunk_repository=mock_chunk_repo,
        )
        pipeline._reload_chunks_from_db = make_fake_reload_chunks(count=1)

        payload = build_payload()
        payload.pdf_parser_backend = "opendataloader"

        result = await pipeline.execute(payload)

        # 验证失败
        assert result.status == PipelineStatus.FAILED

        # 验证 ES 成功但 sparse 失败
        assert "es_write" in order_tracker
        assert "sparse_run" in order_tracker
        assert order_tracker.index("es_write") < order_tracker.index("sparse_run")

        # 验证状态
        assert post_repo.pipeline.pipeline_status == PIPELINE_STATUS_FAILED
        assert post_repo.pipeline.sparse_vectorizing_status == STAGE_STATUS_FAILED
        assert post_repo.pipeline.failed_stage == "SPARSE_VECTORIZING"

        # 验证通知被发送
        mq_service.send.assert_awaited()

    @patch(
        "src.core.pipeline.parse_task.pipeline.ParseTaskService.aprocess",
        new_callable=AsyncMock,
    )
    @patch("src.core.pipeline.parse_task.pipeline.ParseTaskPipeline._chunk_markdown")
    async def test_sparse_executes_after_es_success(
        self,
        mock_chunk_markdown,
        mock_aprocess,
        monkeypatch,
        tmp_path,
    ):
        """验证 sparse 只在 ES 成功后执行。"""
        db = build_db(build_parse_task())
        monkeypatch.setattr(
            "src.core.pipeline.parse_task.pipeline.settings.PARSE_TEMP_DIR",
            str(tmp_path),
        )
        order_tracker = []

        storage = MagicMock()
        storage.download_to_path.side_effect = lambda bucket, object_key, dst: dst.write_bytes(
            b"pdf bytes"
        )
        storage.upload_bytes.side_effect = lambda **kwargs: None

        mq_service = MagicMock()
        mq_service.send = AsyncMock()

        # Mock ChunkRepository instance directly
        mock_chunk_repo = AsyncMock()
        mock_chunk_repo.bulk_insert_pending = AsyncMock()

        vector_storage = OrderTrackingVectorStorage(order_tracker=order_tracker)
        preprocessor = OrderTrackingPreprocessor(order_tracker=order_tracker)
        es_pipeline = OrderTrackingEsIndexingPipeline(order_tracker=order_tracker)
        sparse_pipeline = OrderTrackingSparseIndexingPipeline(order_tracker=order_tracker)
        post_repo = FakePostProcessRepository()

        mock_aprocess.return_value = {
            "markdown": "parsed content",
            "parse_result": MagicMock(),
            "metadata": {"pages_or_length": 3},
            "time_cost_ms": 120,
        }
        mock_chunk_markdown.return_value = [
            Chunk(content="alpha", start_line=1, end_line=1),
        ]

        pipeline = ParseTaskPipeline(
            storage=storage,
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
            vector_storage=vector_storage,
            pipeline_repository=post_repo,
            es_indexing_pipeline=es_pipeline,
            preprocessor=preprocessor,
            sparse_indexing_pipeline=sparse_pipeline,
            chunk_repository=mock_chunk_repo,
        )
        pipeline._reload_chunks_from_db = make_fake_reload_chunks(count=1)

        payload = build_payload()
        payload.pdf_parser_backend = "opendataloader"

        result = await pipeline.execute(payload)

        # 验证成功
        assert result.status == PipelineStatus.SUCCESS

        # 验证 sparse 在 ES 之后执行
        es_index = order_tracker.index("es_write")
        sparse_index = order_tracker.index("sparse_run")
        assert sparse_index > es_index, "sparse 应该在 ES 之后执行"

        # 验证 ES 成功标记在 sparse 之前
        assert "mark_es_success" in post_repo.calls
        assert "mark_sparse_vectorizing_success" in post_repo.calls
        es_success_index = post_repo.calls.index("mark_es_success")
        sparse_success_index = post_repo.calls.index("mark_sparse_vectorizing_success")
        assert sparse_success_index > es_success_index
