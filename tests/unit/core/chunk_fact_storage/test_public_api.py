from src.core.chunk_fact_storage import (
    CHUNK_STATUS_PENDING,
    ES_STATUS_PENDING,
    ChunkPostStatus,
    ChunkFactStorageError,
    ChunkRepository,
    ChunkRepositoryError,
    FactChunkDraft,
    decide_chunk_post_status,
)


def test_should_export_sql_fact_storage_public_api():
    assert CHUNK_STATUS_PENDING == "PENDING"
    assert ES_STATUS_PENDING == "PENDING"
    assert ChunkRepository is not None
    assert FactChunkDraft is not None
    assert ChunkPostStatus.PROCESSING == "processing"
    assert decide_chunk_post_status is not None


def test_should_define_repository_error_as_sql_fact_storage_error():
    assert issubclass(ChunkRepositoryError, ChunkFactStorageError)
