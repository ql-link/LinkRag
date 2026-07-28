from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import ANY, AsyncMock

import pytest

import src.application.wiki_runtime as runtime_module
from src.api.recall_session_auth import SessionAuthContext
from src.application.recall_errors import RecallApiError
from src.application.wiki_runtime import WikiRuntime
from src.core.pipeline.recall.models import RetrieverHit
from src.core.wiki.models import (
    EffectiveWikiScope,
    WikiChunkLocationRecord,
    WikiChunkRecord,
    WikiChunkRefRecord,
    WikiHeadingPathItem,
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


def _location(
    *,
    chunk_id: str = "C1",
    loaded_positions: int = 0,
    position_count: int = 0,
) -> WikiChunkLocationRecord:
    """构造仓储已经完成位置窗口限制后的 Chunk 记录。"""

    return WikiChunkLocationRecord(
        chunk=WikiChunkRecord(chunk_id, 100, 10, f"content-{chunk_id}", "paragraph", 1, 2),
        heading_ids=tuple(range(1, loaded_positions + 1)),
        position_count=position_count,
    )


def _runtime(monkeypatch, *, strict: bool = False, page_size: int = 15):
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
    repository.find_matching_preview_chunk_ids.return_value = frozenset()
    repository.find_visible_chunk_ids.side_effect = lambda _db, chunk_ids, **_kw: frozenset(
        chunk_ids
    )
    repository.load_visible_chunk_locations.side_effect = lambda _db, chunk_ids, **_kw: tuple(
        _location(chunk_id=chunk_id) for chunk_id in chunk_ids
    )
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
        page_size=page_size,
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
    assert exc_info.value.code == "RECALL_INVALID_REQUEST"
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
async def test_preview_ownership_sql_failure_is_internal_even_in_lenient_mode(monkeypatch):
    runtime, repository, bm25 = _runtime(monkeypatch, strict=False)
    repository.find_heading_page.side_effect = [((), False), ((_heading(1),), False)]
    hit = RetrieverHit("c1", 100, 10, 1.0, "bm25")
    bm25.recall_by_dataset.return_value = {10: [hit]}
    runtime._readiness.filter_visible_hits.return_value = [hit]
    repository.find_matching_preview_chunk_ids.side_effect = RuntimeError("mysql down")

    with pytest.raises(RecallApiError) as exc_info:
        await runtime.search(_ctx(), query="gui", dataset_ids=None, doc_ids=None, cursor=None)

    assert exc_info.value.code == "RECALL_INTERNAL_ERROR"
    repository.load_heading_previews.assert_not_awaited()


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
async def test_mixed_search_reserves_future_heading_preview_before_bm25_pagination(monkeypatch):
    """后页标题的固定预览不得先在前页作为 BM25 正文出现。"""

    runtime, repository, bm25 = _runtime(monkeypatch)
    first_prefix_window = tuple(_heading(index) for index in range(1, 16))
    second_prefix_window = tuple(_heading(index) for index in range(6, 16))
    repository.find_heading_page.side_effect = [
        ((), False),
        (first_prefix_window, False),
        (second_prefix_window, False),
    ]
    repository.find_matching_preview_chunk_ids.return_value = frozenset({"C6"})
    repository.load_heading_previews.side_effect = lambda _db, headings, **_kw: {
        item.id: (
            WikiHeadingPreview(item.id, 1, "C6", 0, 600)
            if item.id == 6
            else WikiHeadingPreview(item.id, 0, None, None, None)
        )
        for item in headings
    }
    hits = [
        RetrieverHit(chunk_id, 100, 10, float(30 - rank), "bm25")
        for rank, chunk_id in enumerate(["C6", *(f"C{i}" for i in range(7, 27))])
    ]
    bm25.recall_by_dataset.return_value = {10: hits}
    runtime._readiness.filter_visible_hits.return_value = hits

    first = await runtime.search(_ctx(), query="gui", dataset_ids=None, doc_ids=None, cursor=None)
    second = await runtime.search(
        _ctx(),
        query="gui",
        dataset_ids=None,
        doc_ids=None,
        cursor=first["next_cursor"],
    )

    first_bm25 = [item["chunk_id"] for item in first["results"] if item["result_type"] == "CHUNK"]
    second_preview_ids = [
        item["heading"].get("direct_chunk_preview_id")
        for item in second["results"]
        if item["result_type"] == "HEADING"
    ]
    assert "C6" not in first_bm25
    assert first_bm25[0] == "C7"
    assert len(first_bm25) == 10
    assert "C6" in second_preview_ids
    assert repository.find_matching_preview_chunk_ids.await_count == 2


@pytest.mark.asyncio
async def test_mixed_final_visibility_drops_stale_candidates_and_backfills(monkeypatch):
    runtime, repository, bm25 = _runtime(monkeypatch, page_size=5)
    repository.find_heading_page.side_effect = [((), False), ((), False)]
    hits = [RetrieverHit(f"C{i}", 100, 10, float(10 - i), "bm25") for i in range(1, 8)]
    bm25.recall_by_dataset.return_value = {10: hits}
    runtime._readiness.filter_visible_hits.return_value = hits
    repository.find_visible_chunk_ids.return_value = frozenset({"C3", "C4", "C5", "C6", "C7"})
    repository.find_visible_chunk_ids.side_effect = None

    payload = await runtime.search(_ctx(), query="gui", dataset_ids=None, doc_ids=None, cursor=None)

    assert [item["chunk_id"] for item in payload["results"]] == [
        "C3",
        "C4",
        "C5",
        "C6",
        "C7",
    ]
    assert [item["chunk_id"] for item in payload["chunks"]] == [
        "C3",
        "C4",
        "C5",
        "C6",
        "C7",
    ]
    repository.find_visible_chunk_ids.assert_awaited_once_with(
        ANY,
        ("C1", "C2", "C3", "C4", "C5", "C6", "C7"),
        scope=ANY,
    )


@pytest.mark.asyncio
async def test_mixed_all_stale_candidates_return_empty_200_page(monkeypatch):
    runtime, repository, bm25 = _runtime(monkeypatch, page_size=5)
    repository.find_heading_page.side_effect = [((), False), ((), False)]
    hits = [RetrieverHit(f"C{i}", 100, 10, float(5 - i), "bm25") for i in range(1, 4)]
    bm25.recall_by_dataset.return_value = {10: hits}
    runtime._readiness.filter_visible_hits.return_value = hits
    repository.find_visible_chunk_ids.return_value = frozenset()
    repository.find_visible_chunk_ids.side_effect = None

    payload = await runtime.search(_ctx(), query="gui", dataset_ids=None, doc_ids=None, cursor=None)

    assert payload["results"] == []
    assert payload["chunks"] == []
    assert payload["has_more"] is False
    repository.find_matching_preview_chunk_ids.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_final_visibility_sql_failure_is_internal(monkeypatch):
    runtime, repository, bm25 = _runtime(monkeypatch, strict=False)
    repository.find_heading_page.side_effect = [((), False), ((), False)]
    hit = RetrieverHit("C1", 100, 10, 1.0, "bm25")
    bm25.recall_by_dataset.return_value = {10: [hit]}
    runtime._readiness.filter_visible_hits.return_value = [hit]
    repository.find_visible_chunk_ids.side_effect = RuntimeError("mysql down")

    with pytest.raises(RecallApiError) as exc_info:
        await runtime.search(_ctx(), query="gui", dataset_ids=None, doc_ids=None, cursor=None)

    assert exc_info.value.status_code == 500
    assert exc_info.value.code == "RECALL_INTERNAL_ERROR"
    repository.find_matching_preview_chunk_ids.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_stale_id_is_not_guessed_as_similar_new_chunk(monkeypatch):
    runtime, repository, bm25 = _runtime(monkeypatch)
    repository.find_heading_page.side_effect = [((), False), ((), False)]
    old_hit = RetrieverHit("C1", 100, 10, 1.0, "bm25")
    bm25.recall_by_dataset.return_value = {10: [old_hit]}
    runtime._readiness.filter_visible_hits.return_value = [old_hit]
    # 即使仓储侧出现与请求无关的新 ID，Runtime 也只能做候选 ID 交集，不能猜映射。
    repository.find_visible_chunk_ids.return_value = frozenset({"C2"})
    repository.find_visible_chunk_ids.side_effect = None

    payload = await runtime.search(_ctx(), query="gui", dataset_ids=None, doc_ids=None, cursor=None)

    assert payload["results"] == []
    assert payload["chunks"] == []


@pytest.mark.asyncio
async def test_mixed_continuous_stale_candidates_scan_only_bounded_pool(monkeypatch):
    runtime, repository, bm25 = _runtime(monkeypatch, page_size=3)
    repository.find_heading_page.side_effect = [((), False), ((), False)]
    hits = [RetrieverHit(f"C{i}", 100, 10, float(6 - i), "bm25") for i in range(1, 6)]
    bm25.recall_by_dataset.return_value = {10: hits}
    runtime._readiness.filter_visible_hits.return_value = hits
    repository.find_visible_chunk_ids.return_value = frozenset({"C5"})
    repository.find_visible_chunk_ids.side_effect = None

    payload = await runtime.search(_ctx(), query="gui", dataset_ids=None, doc_ids=None, cursor=None)

    assert [item["chunk_id"] for item in payload["results"]] == ["C5"]
    assert payload["has_more"] is False
    assert repository.find_visible_chunk_ids.await_args.args[1] == tuple(
        f"C{i}" for i in range(1, 6)
    )


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


@pytest.mark.asyncio
async def test_exact_heading_recomputes_current_preview_summary(monkeypatch):
    runtime, repository, bm25 = _runtime(monkeypatch)
    heading = _heading(1)
    repository.find_heading_page.return_value = ((heading,), False)
    repository.load_heading_previews.side_effect = None
    repository.load_heading_previews.return_value = {1: WikiHeadingPreview(1, 2, "C2", 1, 202)}
    repository.load_visible_chunk_locations.side_effect = None
    repository.load_visible_chunk_locations.return_value = (_location(chunk_id="C2"),)

    payload = await runtime.search(
        _ctx(), query="Guide", dataset_ids=None, doc_ids=None, cursor=None
    )

    summary = payload["results"][0]["heading"]
    assert summary["direct_chunk_preview_id"] == "C2"
    assert summary["direct_chunk_count"] == 2
    assert summary["direct_chunks_has_more"] is True
    assert "next_direct_chunk_cursor" in summary
    assert [chunk["chunk_id"] for chunk in payload["chunks"]] == ["C2"]
    bm25.recall_by_dataset.assert_not_awaited()


@pytest.mark.asyncio
async def test_heading_cursor_from_cross_dataset_search_expands_in_document_scope(monkeypatch):
    runtime, repository, _bm25 = _runtime(monkeypatch)
    search_scope = EffectiveWikiScope(7, (10, 20), None, {})
    document_scope = EffectiveWikiScope(7, (10,), (100,), {10: (100,)})
    repository.resolve_scope.side_effect = [search_scope, document_scope]
    repository.find_heading_page.return_value = ((_heading(1),), False)
    repository.load_heading_previews.side_effect = None
    repository.load_heading_previews.return_value = {1: WikiHeadingPreview(1, 2, "C1", 0, 201)}
    repository.load_heading_chunk_page.return_value = (
        (WikiChunkRefRecord(202, 1, "C2"),),
        False,
    )
    ctx = SessionAuthContext(user_id=7, dataset_ids=[10, 20], request_id="req")

    search = await runtime.search(
        ctx,
        query="Guide",
        dataset_ids=[10, 20],
        doc_ids=None,
        cursor=None,
    )
    direct_cursor = search["results"][0]["heading"]["next_direct_chunk_cursor"]
    expanded = await runtime.expand_heading_chunks(
        ctx,
        doc_id=100,
        heading_key=f"{1:064x}",
        cursor=direct_cursor,
    )

    assert [chunk["chunk_id"] for chunk in expanded["chunks"]] == ["C2"]
    assert repository.load_heading_chunk_page.await_args.kwargs["after"] == (0, 201)


@pytest.mark.asyncio
async def test_heading_cursor_rejects_changed_document_dataset(monkeypatch):
    runtime, repository, _bm25 = _runtime(monkeypatch)
    search_scope = EffectiveWikiScope(7, (10, 20), None, {})
    moved_document_scope = EffectiveWikiScope(7, (20,), (100,), {20: (100,)})
    repository.resolve_scope.side_effect = [search_scope, moved_document_scope]
    repository.find_heading_page.return_value = ((_heading(1),), False)
    repository.load_heading_previews.side_effect = None
    repository.load_heading_previews.return_value = {1: WikiHeadingPreview(1, 2, "C1", 0, 201)}
    ctx = SessionAuthContext(user_id=7, dataset_ids=[10, 20], request_id="req")

    search = await runtime.search(
        ctx,
        query="Guide",
        dataset_ids=[10, 20],
        doc_ids=None,
        cursor=None,
    )
    direct_cursor = search["results"][0]["heading"]["next_direct_chunk_cursor"]

    with pytest.raises(RecallApiError) as exc_info:
        await runtime.expand_heading_chunks(
            ctx,
            doc_id=100,
            heading_key=f"{1:064x}",
            cursor=direct_cursor,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "RECALL_INVALID_REQUEST"
    repository.load_heading_chunk_page.assert_not_awaited()


@pytest.mark.asyncio
async def test_exact_heading_recomputes_preview_that_disappears_during_final_hydration(
    monkeypatch,
):
    runtime, repository, bm25 = _runtime(monkeypatch)
    heading = _heading(1)
    repository.find_heading_page.return_value = ((heading,), False)
    repository.load_heading_previews.side_effect = [
        {1: WikiHeadingPreview(1, 2, "C1", 0, 201)},
        {1: WikiHeadingPreview(1, 1, "C2", 1, 202)},
    ]
    repository.load_visible_chunk_locations.side_effect = [
        (),
        (_location(chunk_id="C2"),),
    ]

    payload = await runtime.search(
        _ctx(), query="Guide", dataset_ids=None, doc_ids=None, cursor=None
    )

    summary = payload["results"][0]["heading"]
    assert summary["direct_chunk_preview_id"] == "C2"
    assert summary["direct_chunk_count"] == 1
    assert summary["direct_chunks_has_more"] is False
    assert "next_direct_chunk_cursor" not in summary
    assert [chunk["chunk_id"] for chunk in payload["chunks"]] == ["C2"]
    assert repository.load_heading_previews.await_count == 2
    assert repository.load_visible_chunk_locations.await_count == 2
    bm25.recall_by_dataset.assert_not_awaited()


@pytest.mark.asyncio
async def test_exact_heading_drops_preview_if_bounded_recompute_also_becomes_stale(monkeypatch):
    runtime, repository, _bm25 = _runtime(monkeypatch)
    heading = _heading(1)
    repository.find_heading_page.return_value = ((heading,), False)
    repository.load_heading_previews.side_effect = [
        {1: WikiHeadingPreview(1, 2, "C1", 0, 201)},
        {1: WikiHeadingPreview(1, 1, "C2", 1, 202)},
    ]
    repository.load_visible_chunk_locations.side_effect = [(), ()]

    payload = await runtime.search(
        _ctx(), query="Guide", dataset_ids=None, doc_ids=None, cursor=None
    )

    summary = payload["results"][0]["heading"]
    assert summary["direct_chunk_count"] == 0
    assert summary["direct_chunks_has_more"] is False
    assert "direct_chunk_preview_id" not in summary
    assert "next_direct_chunk_cursor" not in summary
    assert payload["chunks"] == []


@pytest.mark.asyncio
async def test_mixed_final_preview_recompute_removes_same_chunk_from_bm25(monkeypatch):
    runtime, repository, bm25 = _runtime(monkeypatch, page_size=2)
    heading = _heading(1)
    repository.find_heading_page.side_effect = [((), False), ((heading,), False)]
    repository.load_heading_previews.side_effect = [
        {1: WikiHeadingPreview(1, 2, "C1", 0, 201)},
        {1: WikiHeadingPreview(1, 2, "C1", 0, 201)},
        {1: WikiHeadingPreview(1, 1, "C2", 1, 202)},
    ]
    hit = RetrieverHit("C2", 100, 10, 1.0, "bm25")
    bm25.recall_by_dataset.return_value = {10: [hit]}
    runtime._readiness.filter_visible_hits.return_value = [hit]
    repository.load_visible_chunk_locations.side_effect = None
    repository.load_visible_chunk_locations.return_value = (_location(chunk_id="C2"),)

    payload = await runtime.search(_ctx(), query="Gui", dataset_ids=None, doc_ids=None, cursor=None)

    assert [item["result_type"] for item in payload["results"]] == ["HEADING"]
    assert payload["results"][0]["heading"]["direct_chunk_preview_id"] == "C2"
    assert [chunk["chunk_id"] for chunk in payload["chunks"]] == ["C2"]


@pytest.mark.asyncio
async def test_heading_expansion_skips_stale_candidate_and_backfills(monkeypatch):
    runtime, repository, _bm25 = _runtime(monkeypatch, page_size=2)
    refs = tuple(WikiChunkRefRecord(index, index - 1, f"C{index}") for index in range(1, 4))
    repository.load_heading_chunk_page.return_value = (refs, False)
    repository.load_visible_chunk_locations.side_effect = None
    repository.load_visible_chunk_locations.return_value = (
        _location(chunk_id="C2"),
        _location(chunk_id="C3"),
    )

    payload = await runtime.expand_heading_chunks(
        _ctx(), doc_id=100, heading_key="a" * 64, cursor=None
    )

    assert [chunk["chunk_id"] for chunk in payload["chunks"]] == ["C2", "C3"]
    assert payload["direct_chunks_has_more"] is False
    assert repository.load_heading_chunk_page.await_args.kwargs["limit"] == 4


@pytest.mark.asyncio
async def test_heading_expansion_advances_past_all_stale_lookahead_candidates(monkeypatch):
    runtime, repository, _bm25 = _runtime(monkeypatch, page_size=2)
    first_refs = tuple(WikiChunkRefRecord(index, index - 1, f"C{index}") for index in range(1, 5))
    repository.load_heading_chunk_page.side_effect = [
        (first_refs, True),
        ((WikiChunkRefRecord(5, 4, "C5"),), False),
    ]
    repository.load_visible_chunk_locations.side_effect = [
        (),
        (_location(chunk_id="C5"),),
    ]

    first_page = await runtime.expand_heading_chunks(
        _ctx(), doc_id=100, heading_key="a" * 64, cursor=None
    )
    second_page = await runtime.expand_heading_chunks(
        _ctx(),
        doc_id=100,
        heading_key="a" * 64,
        cursor=first_page["next_direct_chunk_cursor"],
    )

    assert first_page["chunks"] == []
    assert first_page["direct_chunks_has_more"] is True
    assert repository.load_heading_chunk_page.await_args_list[1].kwargs["after"] == (3, 4)
    assert [chunk["chunk_id"] for chunk in second_page["chunks"]] == ["C5"]
    assert second_page["direct_chunks_has_more"] is False


@pytest.mark.asyncio
async def test_explicit_location_with_stale_id_remains_strict(monkeypatch):
    runtime, repository, _bm25 = _runtime(monkeypatch)
    repository.load_chunk_locations.side_effect = RecallApiError(
        403, "RECALL_SCOPE_FORBIDDEN", "one or more chunks are not authorized"
    )

    with pytest.raises(RecallApiError) as exc_info:
        await runtime.locate_chunks(_ctx(), chunk_ids=["C1", "C2"], dataset_ids=None)

    assert exc_info.value.status_code == 403
    repository.load_visible_chunk_locations.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("position_count", "positions_truncated"),
    [(10, False), (11, True), (5000, True)],
)
async def test_search_limits_position_hydration_in_repository_and_keeps_total_count(
    monkeypatch, position_count, positions_truncated
):
    runtime, repository, _bm25 = _runtime(monkeypatch)
    repository.find_heading_page.return_value = ((_heading(),), False)
    repository.load_heading_previews.return_value = {1: WikiHeadingPreview(1, 1, "C1", 0, 101)}
    repository.load_heading_previews.side_effect = None
    repository.load_visible_chunk_locations.side_effect = None
    repository.load_visible_chunk_locations.return_value = (
        _location(loaded_positions=min(position_count, 10), position_count=position_count),
    )
    loaded_positions = min(position_count, 10)
    repository.load_headings_by_ids.return_value = tuple(
        _heading(index) for index in range(1, loaded_positions + 1)
    )
    repository.load_heading_paths.return_value = {
        index: (WikiHeadingPathItem(f"{index:064x}", f"H{index}", 1),)
        for index in range(1, loaded_positions + 1)
    }

    payload = await runtime.search(
        _ctx(), query="Guide", dataset_ids=None, doc_ids=None, cursor=None
    )

    repository.load_visible_chunk_locations.assert_awaited_once()
    assert repository.load_visible_chunk_locations.await_args.kwargs["max_positions"] == 10
    assert repository.load_headings_by_ids.await_args.args[1] == list(
        range(1, loaded_positions + 1)
    )
    assert len(payload["chunks"][0]["positions"]) == loaded_positions
    assert payload["chunks"][0]["position_count"] == position_count
    assert payload["chunks"][0]["positions_truncated"] is positions_truncated


@pytest.mark.asyncio
async def test_heading_expansion_limits_positions_but_chunk_location_keeps_full_set(monkeypatch):
    runtime, repository, _bm25 = _runtime(monkeypatch)
    repository.load_heading_chunk_page.return_value = ((WikiChunkRefRecord(101, 0, "C1"),), False)
    repository.load_visible_chunk_locations.side_effect = None
    repository.load_visible_chunk_locations.return_value = (
        _location(loaded_positions=10, position_count=25),
    )
    repository.load_headings_by_ids.return_value = tuple(_heading(index) for index in range(1, 11))

    expanded = await runtime.expand_heading_chunks(
        _ctx(), doc_id=100, heading_key="a" * 64, cursor=None
    )

    assert repository.load_visible_chunk_locations.await_args.kwargs["max_positions"] == 10
    assert len(expanded["chunks"][0]["positions"]) == 10
    repository.load_chunk_locations.return_value = (
        _location(loaded_positions=25, position_count=25),
    )
    repository.load_headings_by_ids.return_value = tuple(_heading(index) for index in range(1, 26))

    located = await runtime.locate_chunks(_ctx(), chunk_ids=["C1"], dataset_ids=None)

    assert "max_positions" not in repository.load_chunk_locations.await_args.kwargs
    assert len(located["locations"][0]["positions"]) == 25
