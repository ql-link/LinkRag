from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.core.wiki.exceptions import WikiCursorError
from src.core.wiki.search_service import (
    Bm25RoundRobin,
    RoundRobinPosition,
    WikiCursorCodec,
    WikiResultMerger,
    make_scope_fingerprint,
)


def test_bm25_round_robin_preserves_dataset_rank_order() -> None:
    page = Bm25RoundRobin.page(
        {30: ["C30-1", "C30-2"], 10: ["C10-1", "C10-2"], 20: ["C20-1", "C20-2"]},
        limit=6,
    )

    assert page.items == ("C10-1", "C20-1", "C30-1", "C10-2", "C20-2", "C30-2")
    assert page.has_more is False


def test_bm25_round_robin_continues_across_pages_with_25_datasets() -> None:
    candidates = {
        dataset_id: [f"C{dataset_id}-1", f"C{dataset_id}-2"] for dataset_id in range(1, 26)
    }

    first = Bm25RoundRobin.page(candidates, limit=10)
    second = Bm25RoundRobin.page(candidates, position=first.next_position, limit=10)
    third = Bm25RoundRobin.page(candidates, position=second.next_position, limit=10)

    assert first.items == tuple(f"C{i}-1" for i in range(1, 11))
    assert second.items == tuple(f"C{i}-1" for i in range(11, 21))
    assert third.items == tuple(
        [*(f"C{i}-1" for i in range(21, 26)), *(f"C{i}-2" for i in range(1, 6))]
    )


def test_bm25_round_robin_skips_empty_datasets() -> None:
    page = Bm25RoundRobin.page({10: [], 20: ["C20-1", "C20-2"], 30: ["C30-1"]}, limit=3)

    assert page.items == ("C20-1", "C30-1", "C20-2")


@pytest.mark.parametrize(
    ("prefix_count", "bm25_count", "expected"),
    [(20, 20, (5, 10)), (4, 20, (4, 11)), (20, 3, (12, 3)), (20, 0, (15, 0)), (0, 20, (0, 15))],
)
def test_result_merger_applies_quota_and_backfill(
    prefix_count: int,
    bm25_count: int,
    expected: tuple[int, int],
) -> None:
    page = WikiResultMerger.merge_page(
        list(range(prefix_count)),
        {10: list(range(bm25_count))},
        page_size=15,
    )

    assert (len(page.prefix_items), len(page.bm25_items)) == expected


def test_result_merger_pages_40_items_without_duplicates() -> None:
    prefixes = list(range(14))
    bm25 = {10: list(range(13)), 20: list(range(13, 26))}
    pages = []
    prefix_offset = 0
    bm25_position = RoundRobinPosition()

    for _ in range(3):
        page = WikiResultMerger.merge_page(
            prefixes,
            bm25,
            page_size=15,
            prefix_offset=prefix_offset,
            bm25_position=bm25_position,
        )
        pages.append([*(f"p{x}" for x in page.prefix_items), *(f"b{x}" for x in page.bm25_items)])
        prefix_offset = page.next_prefix_offset
        bm25_position = page.next_bm25_position

    flattened = [item for page in pages for item in page]
    assert [len(page) for page in pages] == [15, 15, 10]
    assert len(flattened) == len(set(flattened)) == 40


@dataclass(frozen=True)
class _PrefixCandidate:
    id: int


@dataclass(frozen=True)
class _Bm25Candidate:
    chunk_id: str


def test_result_merger_deduplicates_heading_ids_and_chunk_ids_before_paging() -> None:
    prefixes = [
        _PrefixCandidate(1),
        _PrefixCandidate(1),
        _PrefixCandidate(2),
        _PrefixCandidate(3),
    ]
    bm25 = {
        10: [_Bm25Candidate("C1"), _Bm25Candidate("C2")],
        20: [_Bm25Candidate("C1"), _Bm25Candidate("C3")],
    }

    first = WikiResultMerger.merge_page(prefixes, bm25, page_size=3)
    second = WikiResultMerger.merge_page(
        prefixes,
        bm25,
        page_size=3,
        prefix_offset=first.next_prefix_offset,
        bm25_position=first.next_bm25_position,
    )

    assert [item.id for item in first.prefix_items] == [1]
    assert [item.chunk_id for item in first.bm25_items] == ["C1", "C3"]
    assert [item.id for item in second.prefix_items] == [2, 3]
    assert [item.chunk_id for item in second.bm25_items] == ["C2"]
    assert first.has_more is True
    assert second.has_more is False


def test_cursor_is_signed_bound_and_expires_after_ten_minutes() -> None:
    now = [1000.0]
    codec = WikiCursorCodec("secret", clock=lambda: now[0])
    binding = {"user_id": 123, "query": "guide", "scope": "fingerprint"}
    cursor = codec.encode(branch="mixed", binding=binding, state={"prefix_offset": 5})

    assert codec.decode_and_validate(
        cursor,
        expected_branch="mixed",
        expected_binding=binding,
    ) == {"prefix_offset": 5}

    now[0] = 1600.0
    with pytest.raises(WikiCursorError, match="expired"):
        codec.decode_and_validate(cursor, expected_branch="mixed", expected_binding=binding)


def test_cursor_rejects_branch_binding_and_signature_mismatch() -> None:
    codec = WikiCursorCodec("secret", clock=lambda: 1000.0)
    cursor = codec.encode(branch="exact", binding={"query": "guide"}, state={})

    with pytest.raises(WikiCursorError, match="branch"):
        codec.decode_and_validate(
            cursor,
            expected_branch="heading_chunks",
            expected_binding={"query": "guide"},
        )
    with pytest.raises(WikiCursorError, match="binding"):
        codec.decode_and_validate(
            cursor,
            expected_branch="exact",
            expected_binding={"query": "other"},
        )
    with pytest.raises(WikiCursorError, match="signature"):
        codec.decode_and_validate(
            cursor[:-1] + ("A" if cursor[-1] != "A" else "B"),
            expected_branch="exact",
            expected_binding={"query": "guide"},
        )
    for noncanonical in (cursor + "$$", cursor + "="):
        with pytest.raises(WikiCursorError, match="encoding"):
            codec.decode_and_validate(
                noncanonical,
                expected_branch="exact",
                expected_binding={"query": "guide"},
            )


def test_scope_fingerprint_is_order_independent() -> None:
    assert make_scope_fingerprint(
        user_id=123, dataset_ids=[20, 10], doc_ids=[2, 1]
    ) == make_scope_fingerprint(
        user_id=123,
        dataset_ids=[10, 20],
        doc_ids=[1, 2],
    )
