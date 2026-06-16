from __future__ import annotations

from types import SimpleNamespace

from src.core.storage.qdrant import IndexedPoint, SparseIndexedPoint
from src.core.encoding.sparse import SparseVector
from src.core.storage.qdrant.point_factory import (
    indexed_point_from_draft,
    indexed_point_from_record,
    sparse_indexed_point_from_draft,
)


def test_should_create_indexed_point_from_draft_when_embedding_provided():
    draft = SimpleNamespace(
        chunk_id="chunk-1",
        bucket_id=3,
        user_id=7,
        set_id=8,
        doc_id=9,
    )
    embedded_chunk = SimpleNamespace(embedding=[1, "2", 3.5])

    point = indexed_point_from_draft(draft, embedded_chunk)

    assert isinstance(point, IndexedPoint)
    assert point.chunk_id == "chunk-1"
    assert point.bucket_id == 3
    assert point.vector == [1.0, 2.0, 3.5]
    assert point.payload == {
        "chunk_id": "chunk-1",
        "user_id": 7,
        "set_id": 8,
        "doc_id": 9,
    }


def test_should_create_indexed_point_from_record_when_embedding_provided():
    record = SimpleNamespace(
        chunk_id="chunk-2",
        bucket_id=4,
        user_id=17,
        set_id=18,
        doc_id=19,
    )
    embedded_chunk = SimpleNamespace(embedding=[0.1, 0.2])

    point = indexed_point_from_record(record, embedded_chunk)

    assert point == IndexedPoint(
        chunk_id="chunk-2",
        bucket_id=4,
        vector=[0.1, 0.2],
        payload={
            "chunk_id": "chunk-2",
            "user_id": 17,
            "set_id": 18,
            "doc_id": 19,
        },
    )



def test_should_create_sparse_indexed_point_from_draft_when_sparse_vector_provided():
    draft = SimpleNamespace(
        chunk_id="chunk-1",
        bucket_id=3,
        user_id=7,
        set_id=8,
        doc_id=9,
    )
    sparse_vector = SparseVector(indices=[1, 4], values=[0.2, 0.8])

    point = sparse_indexed_point_from_draft(draft, sparse_vector, vector_name="sparse_text")

    assert point == SparseIndexedPoint(
        chunk_id="chunk-1",
        bucket_id=3,
        vector_name="sparse_text",
        sparse_vector=sparse_vector,
        payload={
            "chunk_id": "chunk-1",
            "user_id": 7,
            "set_id": 8,
            "doc_id": 9,
        },
    )
