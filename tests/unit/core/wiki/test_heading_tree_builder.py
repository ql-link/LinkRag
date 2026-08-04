from __future__ import annotations

from dataclasses import replace

import pytest

from src.core.markdown_parser import ElementType, MarkdownElement, ParseResult
from src.core.splitter.models import Chunk
from src.core.storage.vector.models import StoredChunkDraft
from src.core.wiki import HeadingTreeBuilder, WikiTreeBuildError


def _heading(line: int, level: int, title: str) -> MarkdownElement:
    return MarkdownElement(
        type=ElementType.HEADING,
        content=f"{'#' * level} {title}",
        start_line=line,
        end_line=line,
        metadata={"heading_level": level, "heading_text": title},
    )


def _body(line: int, text: str = "body", *, kind: ElementType = ElementType.PARAGRAPH):
    return MarkdownElement(type=kind, content=text, start_line=line, end_line=line)


def _parse(*elements: MarkdownElement) -> ParseResult:
    return ParseResult(elements=list(elements), tables=[], images=[])


def _chunk(start: int, end: int, index: int) -> Chunk:
    return Chunk(
        content=f"chunk-{index}",
        start_line=start,
        end_line=end,
        metadata={"chunk_index": index, "element_types": ["paragraph"]},
    )


def _draft(chunk: Chunk, index: int, *, doc_id: int = 10001) -> StoredChunkDraft:
    return StoredChunkDraft(
        chunk_id=f"C{index}",
        user_id=123,
        set_id=10,
        doc_id=doc_id,
        content=chunk.content,
        content_hash="hash",
        chunk_type="paragraph",
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        chunk_index=index,
    )


def _build(parse_result: ParseResult, chunks: list[Chunk], *, doc_id: int = 10001):
    return HeadingTreeBuilder().build(
        doc_id=doc_id,
        parse_result=parse_result,
        chunks=chunks,
        chunk_drafts=[_draft(chunk, index, doc_id=doc_id) for index, chunk in enumerate(chunks)],
    )


def test_builds_h1_to_h6_in_topological_order() -> None:
    elements: list[MarkdownElement] = []
    for level in range(1, 7):
        elements.extend([_heading(level * 2, level, f"H{level}"), _body(level * 2 + 1)])

    tree = _build(_parse(*elements), [_chunk(3, 3, 0)])

    assert [heading.heading_level for heading in tree.headings] == [1, 2, 3, 4, 5, 6]
    assert tree.headings[0].parent_heading_key is None
    assert [heading.parent_heading_key for heading in tree.headings[1:]] == [
        heading.heading_key for heading in tree.headings[:-1]
    ]


def test_build_uses_physical_line_order_when_parse_elements_are_unsorted() -> None:
    tree = _build(
        _parse(_body(2), _heading(1, 2, "Child"), _heading(0, 1, "Root")),
        [_chunk(2, 2, 0)],
    )

    assert [heading.title for heading in tree.headings] == ["Root", "Child"]
    assert tree.headings[1].parent_heading_key == tree.headings[0].heading_key
    assert tree.chunk_refs[0].parent_heading_key == tree.headings[1].heading_key


def test_duplicate_same_path_headings_remain_distinct_and_mount_by_position() -> None:
    parse_result = _parse(
        _heading(0, 1, "Guide"),
        _heading(1, 2, "安装"),
        _body(2, "first"),
        _heading(3, 2, "安装"),
        _body(4, "second"),
    )

    tree = _build(parse_result, [_chunk(2, 2, 0), _chunk(4, 4, 1)])
    installs = [heading for heading in tree.headings if heading.title == "安装"]

    assert len(installs) == 2
    assert installs[0].heading_key != installs[1].heading_key
    assert [(ref.chunk_id, ref.parent_heading_key) for ref in tree.chunk_refs] == [
        ("C0", installs[0].heading_key),
        ("C1", installs[1].heading_key),
    ]


def test_chunk_mounts_only_to_terminal_headings_and_all_covered_paths() -> None:
    parse_result = _parse(
        _heading(0, 1, "指南"),
        _heading(1, 2, "安装"),
        _body(2),
        _heading(3, 2, "配置"),
        _body(4),
    )

    tree = _build(parse_result, [_chunk(2, 4, 0)])
    by_title = {heading.title: heading.heading_key for heading in tree.headings}

    assert {ref.parent_heading_key for ref in tree.chunk_refs} == {
        by_title["安装"],
        by_title["配置"],
    }
    assert by_title["指南"] not in {ref.parent_heading_key for ref in tree.chunk_refs}


def test_h6_mount_uses_parse_result_position_when_trail_is_incomplete() -> None:
    parse_result = _parse(_heading(0, 6, "细节"), _body(1))
    chunk = _chunk(1, 1, 0)
    chunk.metadata["heading_trail"] = []

    tree = _build(parse_result, [chunk])

    assert tree.chunk_refs[0].parent_heading_key == tree.headings[0].heading_key


def test_unique_full_heading_trail_supplements_missing_physical_intersection() -> None:
    parse_result = _parse(_heading(0, 1, "Guide"), _body(1))
    chunk = _chunk(20, 20, 0)
    chunk.metadata["heading_trail"] = ["Guide"]

    tree = _build(parse_result, [chunk])

    assert tree.chunk_refs[0].parent_heading_key == tree.headings[0].heading_key


def test_ambiguous_heading_trail_never_matches_by_title_globally() -> None:
    parse_result = _parse(
        _heading(0, 1, "Guide"),
        _body(1),
        _heading(2, 1, "Guide"),
        _body(3),
    )
    chunk = _chunk(20, 20, 0)
    chunk.metadata["heading_trail"] = ["Guide"]

    tree = _build(parse_result, [chunk])

    assert tree.chunk_refs == ()


def test_heading_only_overlap_does_not_create_reference_and_derived_body_does() -> None:
    parse_result = _parse(
        _heading(0, 1, "附录"),
        _heading(1, 1, "正文"),
        _body(2, kind=ElementType.IMAGE),
    )
    overlap_chunk = _chunk(0, 0, 0)
    overlap_chunk.content = "overlap mentions 附录"
    derived_chunk = _chunk(2, 2, 1)
    derived_chunk.metadata["chunk_role"] = "derived_element"

    tree = _build(parse_result, [overlap_chunk, derived_chunk])

    assert [ref.chunk_id for ref in tree.chunk_refs] == ["C1"]
    assert tree.chunk_refs[0].parent_heading_key == tree.headings[1].heading_key


def test_empty_direct_heading_is_retained_without_reference() -> None:
    parse_result = _parse(_heading(0, 1, "概览"), _heading(1, 2, "细节"), _body(2))

    tree = _build(parse_result, [_chunk(2, 2, 0)])

    assert [heading.title for heading in tree.headings] == ["概览", "细节"]
    assert [ref.parent_heading_key for ref in tree.chunk_refs] == [tree.headings[1].heading_key]


def test_headingless_document_uses_virtual_root_without_placeholder() -> None:
    tree = _build(_parse(_body(0)), [_chunk(0, 0, 0)])

    assert tree.headings == ()
    assert tree.chunk_refs[0].parent_heading_key is None
    assert tree.stats.root_chunk_ref_count == 1


@pytest.mark.parametrize("change", ["body", "lines", "chunk_id", "case", "sibling"])
def test_non_structural_changes_keep_heading_key(change: str) -> None:
    base = _parse(_heading(0, 1, "Guide"), _heading(1, 2, "Install"), _body(2))
    changed = _parse(_heading(10, 1, "Guide"), _heading(11, 2, "Install"), _body(12, "new"))
    if change == "case":
        changed = _parse(_heading(10, 1, "GUIDE"), _heading(11, 2, "INSTALL"), _body(12))
    if change == "sibling":
        base = _parse(
            _heading(0, 1, "Guide"), _heading(1, 2, "Other"), _heading(2, 2, "Install"), _body(3)
        )
        changed = _parse(
            _heading(0, 1, "Guide"), _heading(1, 2, "Install"), _body(2), _heading(3, 2, "Other")
        )

    original_key = next(h.heading_key for h in _build(base, []).headings if h.title == "Install")
    changed_key = next(
        h.heading_key
        for h in _build(changed, [], doc_id=10001).headings
        if h.title.casefold() == "install"
    )

    assert changed_key == original_key


@pytest.mark.parametrize(
    ("parse_result", "doc_id"),
    [
        (_parse(_heading(0, 1, "Guide"), _heading(1, 2, "Setup")), 10001),
        (_parse(_heading(0, 1, "Guide"), _heading(1, 3, "Install")), 10001),
        (_parse(_heading(0, 1, "Other"), _heading(1, 2, "Install")), 10001),
        (_parse(_heading(0, 1, "Guide"), _heading(1, 2, "Install")), 10002),
    ],
)
def test_structural_identity_changes_create_new_key(
    parse_result: ParseResult,
    doc_id: int,
) -> None:
    original = _build(_parse(_heading(0, 1, "Guide"), _heading(1, 2, "Install")), [])
    changed = _build(parse_result, [], doc_id=doc_id)

    assert changed.headings[-1].heading_key != original.headings[-1].heading_key


def test_input_mismatch_is_rejected_before_persistence() -> None:
    chunk = _chunk(0, 0, 0)
    bad_draft = replace(_draft(chunk, 0), doc_id=999)

    with pytest.raises(WikiTreeBuildError, match="belongs to doc_id"):
        HeadingTreeBuilder().build(
            doc_id=10001,
            parse_result=_parse(_body(0)),
            chunks=[chunk],
            chunk_drafts=[bad_draft],
        )


def test_swapped_same_range_drafts_are_rejected_before_persistence() -> None:
    first = _chunk(1, 1, 0)
    second = _chunk(1, 1, 1)
    drafts = [_draft(second, 1), _draft(first, 0)]

    with pytest.raises(WikiTreeBuildError, match="content differ"):
        HeadingTreeBuilder().build(
            doc_id=10001,
            parse_result=_parse(_heading(0, 1, "Guide"), _body(1)),
            chunks=[first, second],
            chunk_drafts=drafts,
        )
