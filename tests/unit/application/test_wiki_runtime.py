from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

import src.application.wiki_runtime as runtime_module
from src.api.recall_session_auth import SessionAuthContext
from src.application.recall_errors import RecallApiError
from src.application.wiki_runtime import WikiRuntime
from src.core.pipeline.recall.models import RetrieverHit
from src.core.wiki.models import (
    EffectiveWikiScope,
    WikiHeadingPreview,
    WikiHeadingRecord,
)
from src.core.wiki.search_service import WikiCursorCodec


@asynccontextmanager
async def _db_context():
    yield object()


def _heading(node_id: int = 1) -> WikiHeadingRecord:
    return WikiHeadingRecord(
        id=node_id,
        heading_key=f"{node_id:064x}",
        doc_id=100,
        dataset_id=10,
        original_filename="guide.md",
        parent_id=None,
        title="Guide",
        heading_level=1,
        sort_order=0,
    )


def _runtime(monkeypatch, *, strict: bool = False):
    monkeypatch.setattr(runtime_module, "get_db_context", _db_context)
    repository = AsyncMock()
    scope = EffectiveWikiScope(7, (10,), None, {})
    repository.resolve_scope.return_value = scope
    repository.revalidate_visible_headings.side_effect = lambda _db, headings, **_kw: tuple(
        headings
    )
    repository.load_heading_paths.return_value = {1: (), 2: ()}
    repository.load_heading_previews.side_effect = lambda _db, headings, **_kw: {
        heading.id: WikiHeadingPreview(heading.id, 0, None, None, None) for heading in headings
    }
    repository.load_chunk_locations.return_value = ()
    repository.load_headings_by_ids.return_value = ()
    bm25 = AsyncMock()
    bm25.recall_by_dataset.return_value = {10: []}
    readiness = AsyncMock()
    readiness.filter_visible_hits.return_value = []
    runtime = WikiRuntime(
        repository=repository,
        bm25_retriever=bm25,
        readiness_gate=readiness,
        cursor_codec=WikiCursorCodec("secret", clock=lambda: 1000),
        page_size=15,
        bm25_top_k_per_dataset=50,
        strict=strict,
    )
    return runtime, repository, bm25


def _ctx() -> SessionAuthContext:
    return SessionAuthContext(user_id=7, dataset_ids=[10], request_id="req")


@pytest.mark.asyncio
async def test_exact_first_page_and_cursor_pages_never_call_bm25(monkeypatch):
    runtime, repository, bm25 = _runtime(monkeypatch)
    repository.find_heading_page.side_effect = [((_heading(1),), True), ((_heading(2),), False)]

    first = await runtime.search(
        _ctx(), query=" guide ", dataset_ids=None, doc_ids=None, cursor=None
    )
    second = await runtime.search(
        _ctx(),
        query="guide",
        dataset_ids=None,
        doc_ids=None,
        cursor=first["next_cursor"],
    )

    assert first["results"][0]["source"] == "exact_title"
    assert second["results"][0]["heading"]["heading_key"] == f"{2:064x}"
    assert second["has_more"] is False
    bm25.recall_by_dataset.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_cursor_stops_before_heading_or_bm25_queries(monkeypatch):
    runtime, repository, bm25 = _runtime(monkeypatch)

    with pytest.raises(RecallApiError) as exc_info:
        await runtime.search(_ctx(), query="guide", dataset_ids=None, doc_ids=None, cursor="bad")

    assert exc_info.value.status_code == 422
    repository.find_heading_page.assert_not_awaited()
    bm25.recall_by_dataset.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_search_cursor_is_rejected_before_queries(monkeypatch):
    runtime, repository, bm25 = _runtime(monkeypatch)

    with pytest.raises(RecallApiError) as exc_info:
        await runtime.search(_ctx(), query="guide", dataset_ids=None, doc_ids=None, cursor="")

    assert exc_info.value.status_code == 422
    repository.find_heading_page.assert_not_awaited()
    bm25.recall_by_dataset.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_heading_chunk_cursor_is_rejected_before_queries(monkeypatch):
    runtime, repository, _bm25 = _runtime(monkeypatch)

    with pytest.raises(RecallApiError) as exc_info:
        await runtime.expand_heading_chunks(
            _ctx(),
            doc_id=100,
            heading_key="a" * 64,
            cursor="",
        )

    assert exc_info.value.status_code == 422
    repository.load_heading_chunk_page.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_lenient_returns_successful_prefix_and_marks_bm25_failure(monkeypatch):
    runtime, repository, bm25 = _runtime(monkeypatch, strict=False)
    repository.find_heading_page.side_effect = [((), False), ((_heading(1),), False)]
    bm25.recall_by_dataset.side_effect = RuntimeError("backend down")

    payload = await runtime.search(_ctx(), query="gui", dataset_ids=None, doc_ids=None, cursor=None)

    assert payload["failed_sources"] == ["bm25"]
    assert payload["results"][0]["source"] == "title_prefix"


@pytest.mark.asyncio
async def test_mixed_strict_fails_when_one_source_fails(monkeypatch):
    runtime, repository, bm25 = _runtime(monkeypatch, strict=True)
    repository.find_heading_page.side_effect = [((), False), ((), False)]
    bm25.recall_by_dataset.side_effect = RuntimeError("backend down")

    with pytest.raises(RecallApiError) as exc_info:
        await runtime.search(_ctx(), query="gui", dataset_ids=None, doc_ids=None, cursor=None)

    assert exc_info.value.status_code == 500
    assert exc_info.value.code == "RECALL_ALL_SOURCES_FAILED"


@pytest.mark.asyncio
async def test_readiness_sql_failure_is_internal_even_in_lenient_mode(monkeypatch):
    runtime, repository, bm25 = _runtime(monkeypatch, strict=False)
    repository.find_heading_page.side_effect = [((), False), ((_heading(1),), False)]
    hit = RetrieverHit("c1", 100, 10, 1.0, "bm25")
    bm25.recall_by_dataset.return_value = {10: [hit]}
    runtime._readiness.filter_visible_hits.side_effect = RuntimeError("mysql down")

    with pytest.raises(RecallApiError) as exc_info:
        await runtime.search(_ctx(), query="gui", dataset_ids=None, doc_ids=None, cursor=None)

    assert exc_info.value.code == "RECALL_INTERNAL_ERROR"


@pytest.mark.asyncio
async def test_scope_sql_failure_is_mapped_to_internal_error(monkeypatch):
    runtime, repository, _bm25 = _runtime(monkeypatch)
    repository.resolve_scope.side_effect = RuntimeError("mysql down")

    with pytest.raises(RecallApiError) as exc_info:
        await runtime.search(_ctx(), query="guide", dataset_ids=None, doc_ids=None, cursor=None)

    assert exc_info.value.code == "RECALL_INTERNAL_ERROR"
    repository.find_heading_page.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_preview_suppresses_duplicate_bm25_and_backfills(monkeypatch):
    runtime, repository, bm25 = _runtime(monkeypatch)
    heading = _heading(1)
    repository.find_heading_page.side_effect = [((), False), ((heading,), False)]
    repository.load_heading_previews.side_effect = lambda _db, headings, **_kw: {
        item.id: WikiHeadingPreview(item.id, 1, "c1", 0, 100) for item in headings
    }
    hits = [RetrieverHit(f"c{i}", 100 + i, 10, 100.0 - i, "bm25") for i in range(1, 16)]
    bm25.recall_by_dataset.return_value = {10: hits}
    runtime._readiness.filter_visible_hits.return_value = hits

    payload = await runtime.search(_ctx(), query="gui", dataset_ids=None, doc_ids=None, cursor=None)

    chunk_result_ids = [
        item["chunk_id"] for item in payload["results"] if item["result_type"] == "CHUNK"
    ]
    assert chunk_result_ids == [f"c{i}" for i in range(2, 16)]
    assert len(payload["results"]) == 15


@pytest.mark.asyncio
async def test_hydration_revalidates_current_success_and_drops_stale_heading(monkeypatch):
    runtime, repository, bm25 = _runtime(monkeypatch)
    repository.find_heading_page.return_value = ((_heading(1),), False)
    repository.revalidate_visible_headings.return_value = ()
    repository.revalidate_visible_headings.side_effect = None

    payload = await runtime.search(
        _ctx(), query="guide", dataset_ids=None, doc_ids=None, cursor=None
    )

    assert payload["results"] == []
    assert payload["chunks"] == []
    repository.revalidate_visible_headings.assert_awaited_once()
    bm25.recall_by_dataset.assert_not_awaited()
