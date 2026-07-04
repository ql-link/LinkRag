from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.core.splitter.models import Chunk
from src.core.storage.vector.draft_factory import ChunkDraftFactory


def _factory() -> ChunkDraftFactory:
    router = MagicMock()
    router.route_user.return_value = SimpleNamespace(bucket_id=11)
    return ChunkDraftFactory(bucket_router=router)


def _chunk(element_types: list[str] | None, **metadata) -> Chunk:
    resolved_metadata = dict(metadata)
    if element_types is not None:
        resolved_metadata["element_types"] = element_types
    return Chunk(content="content", start_line=0, end_line=0, metadata=resolved_metadata)


def test_build_drafts_resolves_front_matter_chunk_type() -> None:
    drafts = _factory().build_drafts(
        user_id=1,
        set_id=2,
        doc_id=3,
        chunks=[_chunk(["front_matter"])],
    )

    assert drafts[0].chunk_type == "front_matter"


def test_build_drafts_resolves_multiple_element_types_as_mixed() -> None:
    drafts = _factory().build_drafts(
        user_id=1,
        set_id=2,
        doc_id=3,
        chunks=[_chunk(["heading", "paragraph"])],
    )

    assert drafts[0].chunk_type == "mixed"


def test_build_drafts_rejects_missing_element_types_even_with_text_fallback_metadata() -> None:
    with pytest.raises(ValueError, match="element_types"):
        _factory().build_drafts(
            user_id=1,
            set_id=2,
            doc_id=3,
            chunks=[_chunk(None, chunk_type="text")],
        )


@pytest.mark.parametrize("element_type", ["text", "hr", "unknown"])
def test_build_drafts_rejects_unsupported_element_types(element_type: str) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        _factory().build_drafts(
            user_id=1,
            set_id=2,
            doc_id=3,
            chunks=[_chunk([element_type])],
        )


@pytest.mark.parametrize(
    "element_types",
    [
        ["heading", "hr"],
        ["text", "paragraph"],
        ["unknown", "paragraph"],
    ],
)
def test_build_drafts_rejects_unsupported_element_type_inside_mixed_candidate(
    element_types: list[str],
) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        _factory().build_drafts(
            user_id=1,
            set_id=2,
            doc_id=3,
            chunks=[_chunk(element_types)],
        )
