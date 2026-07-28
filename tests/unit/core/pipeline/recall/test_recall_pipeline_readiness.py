"""文档级召回门禁：调用顺序、保序过滤与 fail-closed 单测。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import mysql

from src.core.pipeline.recall import (
    SOURCE_DENSE,
    RecallPipeline,
    RecallRequest,
    RetrieverHit,
)
from src.core.pipeline.recall import document_readiness as readiness_module
from src.core.pipeline.recall.document_readiness import MySqlDocumentReadinessGate
from src.core.pipeline.recall.models import RecallHit
from tests.unit.core.pipeline.recall.conftest import (
    FakeDocumentReadinessGate,
    FakeRetriever,
)


def _raw_hit(
    chunk_id: str,
    score: float,
    *,
    doc_id: int,
    dataset_id: int = 10,
) -> RetrieverHit:
    return RetrieverHit(
        chunk_id=chunk_id,
        doc_id=doc_id,
        dataset_id=dataset_id,
        score=score,
        source=SOURCE_DENSE,
    )


def _fused_hit(
    chunk_id: str,
    *,
    doc_id: int,
    dataset_id: int = 10,
) -> RecallHit:
    return RecallHit(
        chunk_id=chunk_id,
        doc_id=doc_id,
        dataset_id=dataset_id,
        fused_score=1.0,
        scores={SOURCE_DENSE: 1.0},
    )


@pytest.mark.asyncio
async def test_readiness_gate_runs_after_fusion_and_before_top_k():
    """前两名不可见时，排在后面的可见候选应在门禁后补足 top_k。"""
    retriever = FakeRetriever(
        source=SOURCE_DENSE,
        hits=[
            _raw_hit("hidden-1", 1.0, doc_id=1),
            _raw_hit("hidden-2", 0.9, doc_id=1),
            _raw_hit("visible-1", 0.8, doc_id=2),
            _raw_hit("visible-2", 0.7, doc_id=3),
            _raw_hit("visible-3", 0.6, doc_id=4),
        ],
    )
    gate = FakeDocumentReadinessGate(visible_chunk_ids={"visible-1", "visible-2", "visible-3"})
    pipeline = RecallPipeline([retriever], readiness_gate=gate)

    response = await pipeline.execute(
        RecallRequest(user_id=7, query="q", dataset_ids=[10], top_k=2, dense_top_k=10)
    )

    assert [hit.chunk_id for hit in response.hits] == ["visible-1", "visible-2"]
    assert len(gate.calls) == 1
    candidates, user_id = gate.calls[0]
    assert user_id == 7
    # 门禁看到完整融合池，而非已经截成 top_k 的前两名。
    assert [hit.chunk_id for hit in candidates] == [
        "hidden-1",
        "hidden-2",
        "visible-1",
        "visible-2",
        "visible-3",
    ]


@pytest.mark.asyncio
async def test_one_hidden_document_does_not_hide_another_ready_document():
    retriever = FakeRetriever(
        source=SOURCE_DENSE,
        hits=[
            _raw_hit("doc-1-a", 1.0, doc_id=1),
            _raw_hit("doc-2-a", 0.9, doc_id=2),
            _raw_hit("doc-1-b", 0.8, doc_id=1),
        ],
    )
    gate = FakeDocumentReadinessGate(visible_chunk_ids={"doc-2-a"})
    pipeline = RecallPipeline([retriever], readiness_gate=gate)

    response = await pipeline.execute(RecallRequest(user_id=7, query="q", dataset_ids=[10]))

    assert [hit.chunk_id for hit in response.hits] == ["doc-2-a"]


@pytest.mark.asyncio
async def test_readiness_failure_is_fail_closed():
    retriever = FakeRetriever(
        source=SOURCE_DENSE,
        hits=[_raw_hit("c1", 1.0, doc_id=1)],
    )
    gate = FakeDocumentReadinessGate(exc=RuntimeError("mysql unavailable"))
    pipeline = RecallPipeline([retriever], readiness_gate=gate)

    with pytest.raises(RuntimeError, match="mysql unavailable"):
        await pipeline.execute(RecallRequest(user_id=7, query="q", dataset_ids=[10]))


def test_pipeline_requires_explicit_readiness_gate():
    retriever = FakeRetriever(source=SOURCE_DENSE, hits=[])

    with pytest.raises(TypeError, match="readiness_gate"):
        RecallPipeline([retriever])  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_mysql_gate_preserves_order_and_checks_hit_routing_tuple():
    session = MagicMock()
    result = MagicMock()
    # c2 的 MySQL dataset=10，与伪造为 dataset=99 的 hit 不匹配，必须过滤。
    result.all.return_value = [
        ("c3", 3, 10, "ACTIVE", "SUCCESS"),
        ("c1", 1, 10, "ACTIVE", "SUCCESS"),
        ("c2", 2, 10, "ACTIVE", "SUCCESS"),
    ]
    session.execute = AsyncMock(return_value=result)

    @asynccontextmanager
    async def session_context():
        yield session

    gate = MySqlDocumentReadinessGate(session_context_factory=session_context)
    c1 = _fused_hit("c1", doc_id=1)
    c2_stale_payload = _fused_hit("c2", doc_id=2, dataset_id=99)
    c3 = _fused_hit("c3", doc_id=3)

    visible = await gate.filter_visible_hits(
        [c1, c2_stale_payload, c3],
        user_id=7,
    )

    assert visible == [c1, c3]
    assert visible[0] is c1
    assert visible[1] is c3
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_mysql_gate_logs_reliable_aggregate_filter_observability(monkeypatch):
    session = MagicMock()
    result = MagicMock()
    result.all.return_value = [
        ("c1", 1, 10, "ACTIVE", "SUCCESS"),
        ("c2", 2, 10, "REMOVED", "SUCCESS"),
        ("c3", 3, 10, "ACTIVE", "FAILED"),
        ("c4", 4, 10, "ACTIVE", "SUCCESS"),
    ]
    session.execute = AsyncMock(return_value=result)
    observability_logger = MagicMock()
    monkeypatch.setattr(readiness_module, "logger", observability_logger)

    @asynccontextmanager
    async def session_context():
        yield session

    gate = MySqlDocumentReadinessGate(session_context_factory=session_context)
    visible = await gate.filter_visible_hits(
        [
            _fused_hit("c1", doc_id=1),
            _fused_hit("c2", doc_id=2),
            _fused_hit("c3", doc_id=3),
            _fused_hit("c4", doc_id=4),
            _fused_hit("missing", doc_id=5),
        ],
        user_id=7,
    )

    assert [hit.chunk_id for hit in visible] == ["c1", "c4"]
    log_call = observability_logger.info.call_args
    assert "event=filter_complete" in log_call.args[0]
    assert "filter_reason_precedence=" in log_call.args[0]
    assert log_call.args[1:5] == (5, 5, 2, 3)
    assert isinstance(log_call.args[5], int)
    assert log_call.args[6:] == (1, 1, 1)


@pytest.mark.asyncio
async def test_mysql_gate_batches_unique_chunk_ids():
    session = MagicMock()
    first = MagicMock()
    first.all.return_value = [
        ("c1", 1, 10, "ACTIVE", "SUCCESS"),
        ("c2", 2, 10, "ACTIVE", "SUCCESS"),
    ]
    second = MagicMock()
    second.all.return_value = [("c3", 3, 10, "ACTIVE", "SUCCESS")]
    session.execute = AsyncMock(side_effect=[first, second])

    @asynccontextmanager
    async def session_context():
        yield session

    gate = MySqlDocumentReadinessGate(
        session_context_factory=session_context,
        batch_size=2,
    )
    c1 = _fused_hit("c1", doc_id=1)
    c2 = _fused_hit("c2", doc_id=2)
    c3 = _fused_hit("c3", doc_id=3)

    visible = await gate.filter_visible_hits([c1, c1, c2, c3], user_id=7)

    assert visible == [c1, c1, c2, c3]
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_mysql_gate_empty_candidates_do_not_open_session():
    opened = False

    @asynccontextmanager
    async def session_context():
        nonlocal opened
        opened = True
        yield MagicMock()

    gate = MySqlDocumentReadinessGate(session_context_factory=session_context)

    assert await gate.filter_visible_hits([], user_id=7) == []
    assert opened is False


@pytest.mark.asyncio
async def test_mysql_gate_sql_error_is_not_converted_to_allow_all():
    session = MagicMock()
    session.execute = AsyncMock(side_effect=RuntimeError("query failed"))

    @asynccontextmanager
    async def session_context():
        yield session

    gate = MySqlDocumentReadinessGate(session_context_factory=session_context)

    with pytest.raises(RuntimeError, match="query failed"):
        await gate.filter_visible_hits([_fused_hit("c1", doc_id=1)], user_id=7)


def test_mysql_gate_query_returns_current_pipeline_and_lifecycle_classifiers():
    query = MySqlDocumentReadinessGate._build_query(["c1"], user_id=7)
    sql = str(
        query.compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "document_parse_pipeline.task_id COLLATE utf8mb4_unicode_ci" in sql
    assert "document_parse_file.latest_parse_task_id COLLATE utf8mb4_unicode_ci" in sql
    assert "kb_document_chunk.lifecycle_status" in sql
    assert "document_parse_pipeline.pipeline_status" in sql
    assert "LEFT OUTER JOIN document_parse_file" in sql
    assert "LEFT OUTER JOIN document_parse_pipeline" in sql
    assert "kb_document_chunk.user_id = 7" in sql
    assert "kb_index_repair_job" not in sql
