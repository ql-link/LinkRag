from src.core.qdrant_vector_storage import (
    BucketRoute,
    BucketRouter,
    IndexedPoint,
    QdrantIndexStore,
    QdrantStoreError,
    QdrantVectorStorageConfigurationError,
    QdrantVectorStorageError,
)


def test_should_export_public_api_when_imported_from_package():
    assert BucketRoute is not None
    assert BucketRouter is not None
    assert IndexedPoint is not None
    assert QdrantIndexStore is not None
    assert issubclass(QdrantStoreError, QdrantVectorStorageError)
    assert issubclass(QdrantVectorStorageConfigurationError, QdrantVectorStorageError)
