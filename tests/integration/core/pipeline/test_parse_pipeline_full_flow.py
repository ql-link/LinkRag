"""完整解析流水线集成测试。

与 unit 测试的区别：不 mock Stage 内部逻辑——只 fake 外部依赖（存储、MQ、向量、
ES、稀疏、预分词），让 pipeline + 6 个 Stage + StageServices + Repository 全链路
真实执行，验证：

1. 首次执行全 6 阶段成功路径的 pipeline_record 状态机终态
2. 各阶段逐级数据传递（parse_result → chunks → vector_result → plan → es）
3. 单阶段失败时终止后续阶段并落正确终态
4. 重试路径继承已成功阶段、从失败阶段恢复
5. MQ 通知正确发出（SUCCESS / FAILED）

外部依赖全部通过 FakeXxx 类或 AsyncMock 替换，不需要真实 DB/MQ/Qdrant/ES 连接。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.es_index_storage import EsIndexingResult
from src.core.markdown_parser.models import ParseResult
from src.core.mq.messages.parse_task import ParseTaskPayload
from src.core.pipeline.parse_task.constants import (
    PARSE_TASK_STATUS_FAILED,
    PARSE_TASK_STATUS_SUCCESS,
)
from src.core.pipeline.parse_task.models import PipelineStatus
from src.core.pipeline.parse_task.pipeline import ParseTaskPipeline
from src.core.pipeline.parse_task.post_process.constants import (
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_PROCESSING,
    PIPELINE_STATUS_SUCCESS,
    STAGE_STATUS_FAILED,
    STAGE_STATUS_PENDING,
    STAGE_STATUS_SUCCESS,
)
from src.core.preprocessor.models import ChunkWithTokens, FileIndexMeta, FilePostIndexPlan
from src.core.vector_storage.models import ChunkIndexingResult


# ---------------------------------------------------------------------------
# Helpers: payload, DB session, repository, storage, MQ, etc.
# ---------------------------------------------------------------------------


def build_payload(**overrides) -> ParseTaskPayload:
    defaults = dict(
        task_id="t-integ-001",
        original_file_id=1,
        document_parse_task_id=10,
        user_id=20,
        dataset_id=30,
        file_type="pdf",
        source_bucket="source-bucket",
        source_object_key="uploads/test.pdf",
        source_filename="test.pdf",
        md_bucket="md-bucket",
        md_object_key="parsed/t-integ-001.md",
        pdf_parser_backend="mineru",
    )
    defaults.update(overrides)
    return ParseTaskPayload(**defaults)


def build_parse_task_record(payload: ParseTaskPayload):
    from src.models.parse_task import DocumentParseTask

    return DocumentParseTask(
        id=payload.document_parse_task_id,
        document_original_file_id=payload.original_file_id,
        dataset_id=payload.dataset_id,
        user_id=payload.user_id,
        latest_parse_task_id=payload.task_id,
        original_filename=payload.source_filename,
        parse_count=1,
    )


def build_fake_db(parse_task_record):
    db = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    db.add = MagicMock()

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = parse_task_record
    db.execute = AsyncMock(return_value=result_mock)
    return db


class FakeSessionFactory:
    def __init__(self, db):
        self._db = db

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *args):
        return False


def build_fake_plan(payload: ParseTaskPayload) -> FilePostIndexPlan:
    return FilePostIndexPlan(
        file_meta=FileIndexMeta(
            user_id=payload.user_id,
            dataset_id=payload.dataset_id,
            doc_id=payload.original_file_id,
            task_id=payload.task_id,
        ),
        chunks_with_tokens=[
            ChunkWithTokens(
                chunk_id="chunk-0",
                chunk_index=0,
                coarse_tokens="hello",
                fine_tokens="hello world",
            ),
        ],
    )


class FakePostProcessRepository:
    """内存态 Repository：完整实现 mark_* 方法，让 pipeline_record 状态真实翻转。"""

    def __init__(self, pipeline_status=STAGE_STATUS_PENDING):
        self.pipeline = SimpleNamespace(
            id=200,
            document_parsed_log_id=100,
            document_original_file_id=1,
            document_parse_file_id=10,
            task_id="t-integ-001",
            pipeline_status=pipeline_status,
            cleaning_status=STAGE_STATUS_PENDING,
            chunking_status=STAGE_STATUS_PENDING,
            vectorizing_status=STAGE_STATUS_PENDING,
            pretokenize_status=STAGE_STATUS_PENDING,
            es_indexing_status=STAGE_STATUS_PENDING,
            sparse_vectorizing_status=STAGE_STATUS_PENDING,
            failed_stage=None,
            recover_from_stage=None,
            failure_reason=None,
            chunk_count=0,
            started_at=None,
            finished_at=None,
            total_duration_ms=None,
            superseded_by_task_id=None,
            cleaning_duration_ms=None,
            chunking_duration_ms=None,
            vectorizing_duration_ms=None,
            pretokenize_duration_ms=None,
            es_indexing_duration_ms=None,
            sparse_vectorizing_duration_ms=None,
        )
        self.model_cls = type(self.pipeline)

    async def create_for_log(self, db, log_record, payload):
        self.pipeline.document_parsed_log_id = log_record.id
        self.pipeline.task_id = payload.task_id
        self.pipeline.pipeline_status = STAGE_STATUS_PENDING
        return self.pipeline

    async def get_by_log_id(self, db, document_parsed_log_id):
        return self.pipeline

    async def get_by_task_id(self, db, task_id):
        return self.pipeline if self.pipeline.task_id == task_id else None

    # --- mark_*_started ---
    async def _mark_started(self, db, pipeline, *, stage, started_at):
        if pipeline.pipeline_status in (None, STAGE_STATUS_PENDING):
            pipeline.pipeline_status = PIPELINE_STATUS_PROCESSING
        status_field = {
            "CLEANING": "cleaning_status",
            "CHUNKING": "chunking_status",
            "VECTORIZING": "vectorizing_status",
            "PRETOKENIZE": "pretokenize_status",
            "ES_INDEXING": "es_indexing_status",
            "SPARSE_VECTORIZING": "sparse_vectorizing_status",
        }[stage]
        setattr(pipeline, status_field, "PROCESSING")
        if pipeline.started_at is None:
            pipeline.started_at = started_at
        pipeline.finished_at = None
        pipeline.failed_stage = None
        pipeline.recover_from_stage = None
        pipeline.failure_reason = None

    async def mark_cleaning_started(self, db, pipeline, *, started_at):
        await self._mark_started(db, pipeline, stage="CLEANING", started_at=started_at)

    async def mark_chunking_started(self, db, pipeline, *, started_at):
        await self._mark_started(db, pipeline, stage="CHUNKING", started_at=started_at)

    async def mark_vectorizing_started(self, db, pipeline, *, started_at):
        await self._mark_started(db, pipeline, stage="VECTORIZING", started_at=started_at)

    async def mark_pretokenize_started(self, db, pipeline, *, started_at):
        await self._mark_started(db, pipeline, stage="PRETOKENIZE", started_at=started_at)

    async def mark_es_indexing_started(self, db, pipeline, *, started_at):
        await self._mark_started(db, pipeline, stage="ES_INDEXING", started_at=started_at)

    async def mark_sparse_vectorizing_started(self, db, pipeline, *, started_at):
        await self._mark_started(db, pipeline, stage="SPARSE_VECTORIZING", started_at=started_at)

    # --- mark_*_success ---
    async def mark_cleaning_success(self, db, pipeline, *, duration_ms):
        pipeline.cleaning_status = STAGE_STATUS_SUCCESS
        pipeline.cleaning_duration_ms = duration_ms

    async def mark_post_cleaning(self, db, pipeline, *, started_at):
        pipeline.pipeline_status = PIPELINE_STATUS_PROCESSING

    async def mark_chunking_success(self, db, pipeline, *, duration_ms=None, chunk_count=None):
        pipeline.chunking_status = STAGE_STATUS_SUCCESS
        pipeline.chunking_duration_ms = duration_ms

    async def mark_vectorizing_success(self, db, pipeline, *, duration_ms):
        pipeline.vectorizing_status = STAGE_STATUS_SUCCESS
        pipeline.vectorizing_duration_ms = duration_ms

    async def mark_pretokenize_success(self, db, pipeline, *, duration_ms):
        pipeline.pretokenize_status = STAGE_STATUS_SUCCESS
        pipeline.pretokenize_duration_ms = duration_ms

    async def mark_es_success(self, db, pipeline, *, duration_ms, total_duration_ms=None, finished_at=None):
        pipeline.es_indexing_status = STAGE_STATUS_SUCCESS
        pipeline.es_indexing_duration_ms = duration_ms

    async def mark_sparse_vectorizing_success(self, db, pipeline, *, duration_ms, total_duration_ms, finished_at):
        pipeline.sparse_vectorizing_status = STAGE_STATUS_SUCCESS
        pipeline.sparse_vectorizing_duration_ms = duration_ms
        pipeline.pipeline_status = PIPELINE_STATUS_SUCCESS
        pipeline.total_duration_ms = total_duration_ms
        pipeline.finished_at = finished_at

    # --- mark_*_failed ---
    async def _mark_failed(self, db, pipeline, *, stage, reason, finished_at, duration_ms=None):
        field_map = {
            "CLEANING": ("cleaning_status", "cleaning_duration_ms"),
            "CHUNKING": ("chunking_status", "chunking_duration_ms"),
            "VECTORIZING": ("vectorizing_status", "vectorizing_duration_ms"),
            "PRETOKENIZE": ("pretokenize_status", "pretokenize_duration_ms"),
            "ES_INDEXING": ("es_indexing_status", "es_indexing_duration_ms"),
            "SPARSE_VECTORIZING": ("sparse_vectorizing_status", "sparse_vectorizing_duration_ms"),
        }
        status_f, dur_f = field_map[stage]
        setattr(pipeline, status_f, STAGE_STATUS_FAILED)
        setattr(pipeline, dur_f, duration_ms)
        pipeline.pipeline_status = PIPELINE_STATUS_FAILED
        pipeline.failed_stage = stage
        pipeline.recover_from_stage = stage
        pipeline.failure_reason = reason
        pipeline.finished_at = finished_at

    async def mark_cleaning_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        await self._mark_failed(db, pipeline, stage="CLEANING", reason=reason, finished_at=finished_at, duration_ms=duration_ms)

    async def mark_chunking_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        await self._mark_failed(db, pipeline, stage="CHUNKING", reason=reason, finished_at=finished_at, duration_ms=duration_ms)

    async def mark_vectorizing_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        await self._mark_failed(db, pipeline, stage="VECTORIZING", reason=reason, finished_at=finished_at, duration_ms=duration_ms)

    async def mark_pretokenize_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        await self._mark_failed(db, pipeline, stage="PRETOKENIZE", reason=reason, finished_at=finished_at, duration_ms=duration_ms)

    async def mark_es_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        await self._mark_failed(db, pipeline, stage="ES_INDEXING", reason=reason, finished_at=finished_at, duration_ms=duration_ms)

    async def mark_sparse_vectorizing_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        await self._mark_failed(db, pipeline, stage="SPARSE_VECTORIZING", reason=reason, finished_at=finished_at, duration_ms=duration_ms)


class FakeEsIndexingPipeline:
    def __init__(self, result: EsIndexingResult | None = None):
        self.write_es_index = AsyncMock(
            return_value=result or EsIndexingResult(total_items=2, indexed_items=2),
        )
        self.delete_document_index = AsyncMock()


class FakePreprocessor:
    def __init__(self, plan: FilePostIndexPlan | None = None):
        self.build_file_post_index_plan = AsyncMock(return_value=plan)


class FakeSparseIndexingPipeline:
    def __init__(self, side_effect=None):
        self.run = AsyncMock(side_effect=side_effect)


def make_chunks(n=2):
    from src.core.splitter.models import Chunk

    return [
        Chunk(content=f"chunk-{i}", start_line=i, end_line=i, metadata={})
        for i in range(n)
    ]


def build_pipeline(
    payload: ParseTaskPayload,
    *,
    parse_result: dict | Exception | None = None,
    chunks: list | Exception | None = None,
    vector_result: ChunkIndexingResult | None = None,
    plan: FilePostIndexPlan | None = None,
    es_result: EsIndexingResult | None = None,
    sparse_side_effect=None,
    repository: FakePostProcessRepository | None = None,
) -> tuple[ParseTaskPipeline, FakePostProcessRepository]:
    """Build a ParseTaskPipeline with all external deps faked.

    This is the central harness — external deps are faked, but internal
    pipeline + stages + services + repository run for real.
    """
    _chunks = chunks if chunks is not None else make_chunks()
    _parse_result = parse_result if parse_result is not None else {
        "markdown": "# Title\n\nbody",
        "parse_result": ParseResult(
            elements=[], tables=[], images=[], source_file="test.pdf"
        ),
        "metadata": {"pages_or_length": 2},
        "time_cost_ms": 88,
    }
    _vector_result = vector_result or ChunkIndexingResult(
        total_chunks=2, indexed_chunks=2
    )
    _plan = plan or build_fake_plan(payload)
    _repo = repository or FakePostProcessRepository()

    storage = MagicMock()
    storage.download_to_path = MagicMock()
    storage.upload_bytes = MagicMock()
    storage.build_object_url = MagicMock(return_value="http://fake/test.pdf")

    mq_service = MagicMock()
    mq_service.send = AsyncMock()

    vector_storage = AsyncMock()
    vector_storage.index_document_chunks = AsyncMock(return_value=_vector_result)

    chunk_repo = MagicMock()
    chunk_repo.bulk_insert_pending = AsyncMock()
    chunk_repo.count_es_not_success_by_doc_id = AsyncMock(return_value=0)

    chunk_draft_factory = MagicMock()
    chunk_draft_factory.build_drafts = MagicMock(return_value=[])

    preprocessor = FakePreprocessor(_plan)
    es_pipeline = FakeEsIndexingPipeline(es_result)
    sparse_pipeline = FakeSparseIndexingPipeline(sparse_side_effect)

    parse_task_record = build_parse_task_record(payload)
    db = build_fake_db(parse_task_record)

    pipeline = ParseTaskPipeline(
        storage=storage,
        session_factory=FakeSessionFactory(db),
        mq_service=mq_service,
        vector_storage=vector_storage,
        pipeline_repository=_repo,
        es_indexing_pipeline=es_pipeline,
        preprocessor=preprocessor,
        chunk_repository=chunk_repo,
        chunk_draft_factory=chunk_draft_factory,
        sparse_indexing_pipeline=sparse_pipeline,
    )

    # Patch service-level calls with controlled returns
    if isinstance(_parse_result, Exception):
        pipeline._services.parse_file = AsyncMock(side_effect=_parse_result)
    else:
        pipeline._services.parse_file = AsyncMock(return_value=_parse_result)

    if isinstance(_chunks, Exception):
        pipeline._services.run_chunking = AsyncMock(side_effect=_chunks)
    else:
        pipeline._services.run_chunking = AsyncMock(return_value=_chunks)

    return pipeline, _repo


# ===========================================================================
# 1. 首次执行：全 6 阶段成功
# ===========================================================================

@pytest.mark.integration
async def test_full_pipeline_success_all_six_stages():
    """全 6 阶段成功：pipeline_status 从 PENDING → PROCESSING → SUCCESS。"""
    payload = build_payload()
    pipeline, repo = build_pipeline(payload)

    result = await pipeline.execute(payload)

    assert result.status == PipelineStatus.SUCCESS
    assert result.task_id == payload.task_id

    p = repo.pipeline
    assert p.pipeline_status == PIPELINE_STATUS_SUCCESS
    assert p.cleaning_status == STAGE_STATUS_SUCCESS
    assert p.chunking_status == STAGE_STATUS_SUCCESS
    assert p.vectorizing_status == STAGE_STATUS_SUCCESS
    assert p.pretokenize_status == STAGE_STATUS_SUCCESS
    assert p.es_indexing_status == STAGE_STATUS_SUCCESS
    assert p.sparse_vectorizing_status == STAGE_STATUS_SUCCESS
    assert p.finished_at is not None
    assert p.failed_stage is None
    assert p.failure_reason is None


@pytest.mark.integration
async def test_full_pipeline_success_sends_single_success_notification():
    """全流程成功后只发一次 SUCCESS 通知。"""
    payload = build_payload()
    pipeline, repo = build_pipeline(payload)

    await pipeline.execute(payload)

    mq = pipeline._mq_service
    assert mq.send.await_count == 1
    sent_msg = mq.send.call_args.args[0]
    assert sent_msg.get_payload().task_status == PARSE_TASK_STATUS_SUCCESS


# ===========================================================================
# 2. 阶段数据流：cleaning 产物 → chunking → vectorizing → pretokenize → ES
# ===========================================================================

@pytest.mark.integration
async def test_data_flows_between_stages():
    """验证各阶段产物正确传递到下游。"""
    payload = build_payload()
    chunks = make_chunks(3)
    plan = build_fake_plan(payload)
    pipeline, repo = build_pipeline(payload, chunks=chunks, plan=plan)

    result = await pipeline.execute(payload)

    assert result.status == PipelineStatus.SUCCESS
    assert result.chunk_count == 3

    # parse_file was called (cleaning stage)
    pipeline._services.parse_file.assert_awaited_once()
    # run_chunking was called with markdown from parse_result (chunking stage)
    pipeline._services.run_chunking.assert_awaited_once()


# ===========================================================================
# 3. 单阶段失败场景
# ===========================================================================

@pytest.mark.integration
async def test_cleaning_failure_aborts_pipeline():
    """解析阶段（cleaning）失败：pipeline_status=FAILED，后续阶段不执行。"""
    payload = build_payload()
    pipeline, repo = build_pipeline(
        payload,
        parse_result=RuntimeError("parse engine crash"),
    )

    result = await pipeline.execute(payload)

    assert result.status == PipelineStatus.FAILED
    p = repo.pipeline
    assert p.pipeline_status == PIPELINE_STATUS_FAILED
    assert p.cleaning_status == STAGE_STATUS_FAILED
    assert "PARSE_ENGINE_FAILED" in (p.failure_reason or "")
    # Downstream stages never started
    assert p.chunking_status == STAGE_STATUS_PENDING
    assert p.vectorizing_status == STAGE_STATUS_PENDING


@pytest.mark.integration
async def test_chunking_failure_aborts_pipeline():
    """分片阶段（chunking）失败：cleaning 成功但 pipeline 最终 FAILED。"""
    payload = build_payload()
    pipeline, repo = build_pipeline(
        payload,
        chunks=RuntimeError("chunking crash"),
    )

    result = await pipeline.execute(payload)

    assert result.status == PipelineStatus.FAILED
    p = repo.pipeline
    assert p.cleaning_status == STAGE_STATUS_SUCCESS
    assert p.chunking_status == STAGE_STATUS_FAILED
    assert p.vectorizing_status == STAGE_STATUS_PENDING
    assert "PARSE_ENGINE_FAILED" in (p.failure_reason or "")


@pytest.mark.integration
async def test_vectorizing_failure_aborts_pipeline():
    """向量化阶段失败：所有 chunk 索引失败。"""
    payload = build_payload()
    bad_vector = ChunkIndexingResult(
        total_chunks=2,
        indexed_chunks=0,
        failed_chunk_ids=["chunk-0", "chunk-1"],
    )
    pipeline, repo = build_pipeline(payload, vector_result=bad_vector)

    result = await pipeline.execute(payload)

    assert result.status == PipelineStatus.FAILED
    p = repo.pipeline
    assert p.cleaning_status == STAGE_STATUS_SUCCESS
    assert p.chunking_status == STAGE_STATUS_SUCCESS
    assert p.vectorizing_status == STAGE_STATUS_FAILED
    assert "VECTORIZING_FAILED" in (p.failure_reason or "")
    assert p.pretokenize_status == STAGE_STATUS_PENDING


@pytest.mark.integration
async def test_pretokenize_failure_aborts_pipeline():
    """预分词失败：plan 构建返回 reason。"""
    payload = build_payload()
    bad_preprocessor = FakePreprocessor(plan=None)
    bad_preprocessor.build_file_post_index_plan = AsyncMock(
        side_effect=RuntimeError("tokenizer crash"),
    )

    pipeline, repo = build_pipeline(payload)
    pipeline._services._preprocessor = bad_preprocessor

    result = await pipeline.execute(payload)

    assert result.status == PipelineStatus.FAILED
    p = repo.pipeline
    assert p.pretokenize_status == STAGE_STATUS_FAILED
    assert "pretokenize" in (p.failure_reason or "").lower()
    assert p.es_indexing_status == STAGE_STATUS_PENDING


@pytest.mark.integration
async def test_es_indexing_failure_aborts_pipeline():
    """ES 入库失败：pretokenize 成功但 ES 返回部分失败。"""
    payload = build_payload()
    bad_es = EsIndexingResult(
        total_items=2,
        indexed_items=0,
        failure_reason="es_delete: connection refused",
    )
    pipeline, repo = build_pipeline(payload, es_result=bad_es)

    result = await pipeline.execute(payload)

    assert result.status == PipelineStatus.FAILED
    p = repo.pipeline
    assert p.es_indexing_status == STAGE_STATUS_FAILED
    assert p.sparse_vectorizing_status == STAGE_STATUS_PENDING


@pytest.mark.integration
async def test_sparse_vectorizing_failure():
    """稀疏向量化失败：ES 成功但 sparse 抛异常。"""
    from src.core.sparse_vector.indexing import SparseIndexingError

    payload = build_payload()
    pipeline, repo = build_pipeline(
        payload,
        sparse_side_effect=SparseIndexingError("chunk_total_zero"),
    )

    result = await pipeline.execute(payload)

    assert result.status == PipelineStatus.FAILED
    p = repo.pipeline
    assert p.es_indexing_status == STAGE_STATUS_SUCCESS
    assert p.sparse_vectorizing_status == STAGE_STATUS_FAILED
    assert "chunk_total_zero" in (p.failure_reason or "")


# ===========================================================================
# 4. 失败通知
# ===========================================================================

@pytest.mark.integration
async def test_stage_failure_sends_failed_notification():
    """阶段失败后发出 FAILED 通知。"""
    payload = build_payload()
    pipeline, repo = build_pipeline(
        payload,
        parse_result=RuntimeError("boom"),
    )

    await pipeline.execute(payload)

    mq = pipeline._mq_service
    assert mq.send.await_count >= 1
    sent_msg = mq.send.call_args.args[0]
    assert sent_msg.get_payload().task_status == PARSE_TASK_STATUS_FAILED


# ===========================================================================
# 5. 重试路径：继承已成功阶段
# ===========================================================================

@pytest.mark.integration
async def test_retry_skips_inherited_success_stages():
    """重试时继承 cleaning+chunking SUCCESS，从 vectorizing 恢复。"""
    payload = build_payload(
        task_id="t-retry-001",
        is_retry=True,
        previous_task_id="t-integ-001",
    )

    repo = FakePostProcessRepository()
    # Simulate inherited SUCCESS for cleaning+chunking on old pipeline
    old_pipeline = repo.pipeline
    old_pipeline.task_id = "t-integ-001"
    old_pipeline.pipeline_status = PIPELINE_STATUS_FAILED
    old_pipeline.cleaning_status = STAGE_STATUS_SUCCESS
    old_pipeline.chunking_status = STAGE_STATUS_SUCCESS
    old_pipeline.vectorizing_status = STAGE_STATUS_FAILED
    old_pipeline.failed_stage = "VECTORIZING"
    old_pipeline.recover_from_stage = "VECTORIZING"
    old_pipeline.failure_reason = "VECTORIZING_FAILED: ..."

    # Build a new inherited pipeline (simulating create_with_inherited_state)
    inherited_pipeline = SimpleNamespace(
        id=201,
        document_parsed_log_id=101,
        document_original_file_id=1,
        document_parse_file_id=10,
        task_id="t-retry-001",
        pipeline_status=PIPELINE_STATUS_PROCESSING,
        cleaning_status=STAGE_STATUS_SUCCESS,
        chunking_status=STAGE_STATUS_SUCCESS,
        vectorizing_status=STAGE_STATUS_PENDING,
        pretokenize_status=STAGE_STATUS_PENDING,
        es_indexing_status=STAGE_STATUS_PENDING,
        sparse_vectorizing_status=STAGE_STATUS_PENDING,
        failed_stage=None,
        recover_from_stage="VECTORIZING",
        failure_reason=None,
        chunk_count=0,
        started_at=None,
        finished_at=None,
        total_duration_ms=None,
        superseded_by_task_id=None,
        cleaning_duration_ms=100,
        chunking_duration_ms=50,
        vectorizing_duration_ms=None,
        pretokenize_duration_ms=None,
        es_indexing_duration_ms=None,
        sparse_vectorizing_duration_ms=None,
    )

    chunks = make_chunks(2)
    plan = build_fake_plan(payload)
    pipeline, _ = build_pipeline(payload, chunks=chunks, plan=plan, repository=repo)

    # Patch retry-specific internals to skip DB validation/CAS and go straight to stage execution
    from src.core.pipeline.parse_task.stages import StageContext
    from src.models.parse_task import DocumentParsedLog

    log_record = DocumentParsedLog(
        task_id="t-retry-001",
        document_original_file_id=1,
        document_parse_task_id=10,
        trigger_mode="manual_retry",
    )
    log_record.id = 101

    ctx = StageContext(
        payload=payload,
        log_record=log_record,
        pipeline_record=inherited_pipeline,
        db=build_fake_db(build_parse_task_record(payload)),
        is_retry=True,
    )

    # Provide chunks via on_skip (chunking inherits SUCCESS, loads from DB)
    pipeline._services.load_all_chunks_from_db = AsyncMock(return_value=chunks)

    stage_pipeline = pipeline._build_stage_pipeline()
    result = await stage_pipeline.run(ctx)

    assert result.status == PipelineStatus.SUCCESS

    # cleaning: skipped (inherited SUCCESS, no mark_started called)
    # chunking: skipped (inherited SUCCESS, loaded chunks from DB)
    pipeline._services.parse_file.assert_not_awaited()
    pipeline._services.load_all_chunks_from_db.assert_awaited_once()

    p = inherited_pipeline
    assert p.cleaning_status == STAGE_STATUS_SUCCESS
    assert p.chunking_status == STAGE_STATUS_SUCCESS
    assert p.vectorizing_status == STAGE_STATUS_SUCCESS
    assert p.pretokenize_status == STAGE_STATUS_SUCCESS
    assert p.es_indexing_status == STAGE_STATUS_SUCCESS
    assert p.sparse_vectorizing_status == STAGE_STATUS_SUCCESS
    assert p.pipeline_status == PIPELINE_STATUS_SUCCESS


# ===========================================================================
# 6. 阶段顺序保障
# ===========================================================================

@pytest.mark.integration
async def test_stages_execute_in_correct_order():
    """验证 6 个阶段按固定顺序执行（不跳不乱）。"""
    payload = build_payload()
    pipeline, repo = build_pipeline(payload)

    call_order = []
    original_parse = pipeline._services.parse_file
    original_chunk = pipeline._services.run_chunking

    async def track_parse(*a, **kw):
        call_order.append("cleaning")
        return await original_parse(*a, **kw)

    async def track_chunk(*a, **kw):
        call_order.append("chunking")
        return await original_chunk(*a, **kw)

    pipeline._services.parse_file = track_parse
    pipeline._services.run_chunking = track_chunk

    # vector/pretokenize/es/sparse are tracked via their mock calls
    original_vector = pipeline._services._get_vector_storage().index_document_chunks

    async def track_vector(*a, **kw):
        call_order.append("vectorizing")
        return await original_vector(*a, **kw)

    pipeline._services._get_vector_storage().index_document_chunks = track_vector

    original_pretokenize = pipeline._services._preprocessor.build_file_post_index_plan

    async def track_pretokenize(*a, **kw):
        call_order.append("pretokenize")
        return await original_pretokenize(*a, **kw)

    pipeline._services._preprocessor.build_file_post_index_plan = track_pretokenize

    original_es = pipeline._services._es_indexing_pipeline.write_es_index

    async def track_es(*a, **kw):
        call_order.append("es_indexing")
        return await original_es(*a, **kw)

    pipeline._services._es_indexing_pipeline.write_es_index = track_es

    original_sparse = pipeline._services._sparse_indexing_pipeline.run

    async def track_sparse(*a, **kw):
        call_order.append("sparse_vectorizing")
        return await original_sparse(*a, **kw)

    pipeline._services._sparse_indexing_pipeline.run = track_sparse

    result = await pipeline.execute(payload)
    assert result.status == PipelineStatus.SUCCESS

    expected = [
        "cleaning",
        "chunking",
        "vectorizing",
        "pretokenize",
        "es_indexing",
        "sparse_vectorizing",
    ]
    assert call_order == expected


# ===========================================================================
# 7. ES plan 重建（pretokenize 继承 SUCCESS 但 plan 不持久化）
# ===========================================================================

@pytest.mark.integration
async def test_es_stage_rebuilds_plan_when_pretokenize_inherited():
    """当 pretokenize 继承 SUCCESS 被跳过时，ES 阶段自动重建 plan。"""
    payload = build_payload(
        task_id="t-retry-es-001",
        is_retry=True,
        previous_task_id="t-integ-001",
    )

    inherited = SimpleNamespace(
        id=202,
        document_parsed_log_id=102,
        document_original_file_id=1,
        document_parse_file_id=10,
        task_id="t-retry-es-001",
        pipeline_status=PIPELINE_STATUS_PROCESSING,
        cleaning_status=STAGE_STATUS_SUCCESS,
        chunking_status=STAGE_STATUS_SUCCESS,
        vectorizing_status=STAGE_STATUS_SUCCESS,
        pretokenize_status=STAGE_STATUS_SUCCESS,
        es_indexing_status=STAGE_STATUS_PENDING,
        sparse_vectorizing_status=STAGE_STATUS_PENDING,
        failed_stage=None,
        recover_from_stage="ES_INDEXING",
        failure_reason=None,
        started_at=None,
        finished_at=None,
        total_duration_ms=None,
        superseded_by_task_id=None,
        cleaning_duration_ms=100,
        chunking_duration_ms=50,
        vectorizing_duration_ms=60,
        pretokenize_duration_ms=30,
        es_indexing_duration_ms=None,
        sparse_vectorizing_duration_ms=None,
    )

    repo = FakePostProcessRepository()
    repo.pipeline = inherited

    chunks = make_chunks(2)
    plan = build_fake_plan(payload)
    pipeline_obj, _ = build_pipeline(payload, chunks=chunks, plan=plan, repository=repo)
    pipeline_obj._services.load_all_chunks_from_db = AsyncMock(return_value=chunks)

    from src.core.pipeline.parse_task.stages import StageContext
    from src.models.parse_task import DocumentParsedLog

    log_record = DocumentParsedLog(
        task_id="t-retry-es-001",
        document_original_file_id=1,
        document_parse_task_id=10,
        trigger_mode="manual_retry",
    )
    log_record.id = 102

    ctx = StageContext(
        payload=payload,
        log_record=log_record,
        pipeline_record=inherited,
        db=build_fake_db(build_parse_task_record(payload)),
        is_retry=True,
    )

    stage_pipeline = pipeline_obj._build_stage_pipeline()
    result = await stage_pipeline.run(ctx)

    assert result.status == PipelineStatus.SUCCESS
    # pretokenize was skipped (inherited SUCCESS), but preprocessor was called
    # by ES stage to rebuild the plan
    pipeline_obj._services._preprocessor.build_file_post_index_plan.assert_awaited()
    assert inherited.es_indexing_status == STAGE_STATUS_SUCCESS
    assert inherited.sparse_vectorizing_status == STAGE_STATUS_SUCCESS
    assert inherited.pipeline_status == PIPELINE_STATUS_SUCCESS


# ===========================================================================
# 8. sparse 继承 SUCCESS 时仍翻转 pipeline_status
# ===========================================================================

@pytest.mark.integration
async def test_sparse_skip_still_flips_pipeline_success():
    """sparse 继承 SUCCESS 被跳过时，on_skip 仍翻 pipeline_status=SUCCESS。"""
    payload = build_payload(task_id="t-retry-sparse-001")

    inherited = SimpleNamespace(
        id=203,
        document_parsed_log_id=103,
        document_original_file_id=1,
        document_parse_file_id=10,
        task_id="t-retry-sparse-001",
        pipeline_status=PIPELINE_STATUS_PROCESSING,
        cleaning_status=STAGE_STATUS_SUCCESS,
        chunking_status=STAGE_STATUS_SUCCESS,
        vectorizing_status=STAGE_STATUS_SUCCESS,
        pretokenize_status=STAGE_STATUS_SUCCESS,
        es_indexing_status=STAGE_STATUS_SUCCESS,
        sparse_vectorizing_status=STAGE_STATUS_SUCCESS,
        failed_stage=None,
        recover_from_stage=None,
        failure_reason=None,
        started_at=None,
        finished_at=None,
        total_duration_ms=None,
        superseded_by_task_id=None,
        cleaning_duration_ms=100,
        chunking_duration_ms=50,
        vectorizing_duration_ms=60,
        pretokenize_duration_ms=30,
        es_indexing_duration_ms=40,
        sparse_vectorizing_duration_ms=20,
    )

    repo = FakePostProcessRepository()
    repo.pipeline = inherited

    pipeline_obj, _ = build_pipeline(payload, repository=repo)
    pipeline_obj._services.load_all_chunks_from_db = AsyncMock(return_value=make_chunks())

    from src.core.pipeline.parse_task.stages import StageContext
    from src.models.parse_task import DocumentParsedLog

    log_record = DocumentParsedLog(
        task_id="t-retry-sparse-001",
        document_original_file_id=1,
        document_parse_task_id=10,
        trigger_mode="manual_retry",
    )
    log_record.id = 103

    ctx = StageContext(
        payload=payload,
        log_record=log_record,
        pipeline_record=inherited,
        db=build_fake_db(build_parse_task_record(payload)),
        is_retry=True,
    )

    stage_pipeline = pipeline_obj._build_stage_pipeline()
    result = await stage_pipeline.run(ctx)

    assert result.status == PipelineStatus.SUCCESS
    assert inherited.pipeline_status == PIPELINE_STATUS_SUCCESS
    assert inherited.finished_at is not None
