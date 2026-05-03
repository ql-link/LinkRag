import hashlib
from unittest.mock import patch

from src.core.chunk_fact_storage.constants import CHUNK_STATUS_PENDING
from src.core.qdrant_vector_storage import BucketRoute
from src.core.splitter.models import Chunk
from src.core.vector_storage.draft_factory import ChunkDraftFactory


def test_should_build_drafts_with_hash_and_metadata_when_chunk_fields_are_complete(
    mock_bucket_router,
):
    # Arrange: 准备数据
    mock_bucket_router.route_user.return_value = BucketRoute(
        bucket_id=5,
        collection_name="kb_bucket_5",
    )
    chunks = [
        Chunk(
            content="first chunk",
            start_line=1,
            end_line=3,
            metadata={"element_types": ["paragraph"], "chunk_index": 7},
        ),
        Chunk(
            content="second chunk",
            start_line=4,
            end_line=6,
            metadata={"element_types": ["table", "paragraph"]},
        ),
        Chunk(
            content="fallback chunk",
            start_line=7,
            end_line=9,
            metadata={"type": "code_block"},
        ),
    ]
    factory = ChunkDraftFactory(bucket_router=mock_bucket_router)

    # Act: 执行动作
    with patch(
        "src.core.vector_storage.draft_factory.uuid4",
        side_effect=["uuid-1", "uuid-2", "uuid-3"],
    ):
        drafts = factory.build_drafts(user_id=42, set_id=1001, doc_id=2002, chunks=chunks)

    # Assert: 断言结果
    mock_bucket_router.route_user.assert_called_once_with(42)
    assert len(drafts) == 3
    assert [draft.chunk_id for draft in drafts] == ["uuid-1", "uuid-2", "uuid-3"]
    assert {draft.bucket_id for draft in drafts} == {5}

    assert drafts[0].content == "first chunk"
    assert drafts[0].content_hash == hashlib.sha256(b"first chunk").hexdigest()
    assert drafts[0].chunk_type == "paragraph"
    assert drafts[0].chunk_index == 7
    assert drafts[0].status == CHUNK_STATUS_PENDING

    assert drafts[1].chunk_type == "mixed"
    assert drafts[1].chunk_index is None

    assert drafts[2].chunk_type == "code_block"


def test_should_use_text_chunk_type_when_metadata_type_is_missing(mock_bucket_router):
    # Arrange: 准备数据
    mock_bucket_router.route_user.return_value = BucketRoute(
        bucket_id=9,
        collection_name="kb_bucket_9",
    )
    chunk = Chunk(content="plain", start_line=1, end_line=1, metadata={})
    factory = ChunkDraftFactory(bucket_router=mock_bucket_router)

    # Act: 执行动作
    with patch("src.core.vector_storage.draft_factory.uuid4", return_value="uuid-text"):
        draft = factory.build_drafts(user_id=1, set_id=2, doc_id=3, chunks=[chunk])[0]

    # Assert: 断言结果
    mock_bucket_router.route_user.assert_called_once_with(1)
    assert draft.chunk_type == "text"
    assert draft.chunk_id == "uuid-text"
    assert draft.bucket_id == 9
