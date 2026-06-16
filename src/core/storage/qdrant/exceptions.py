class QdrantVectorStorageError(Exception):
    """Base error for Qdrant vector index storage."""


class QdrantVectorStorageConfigurationError(QdrantVectorStorageError):
    """Raised when Qdrant vector storage dependencies or settings are invalid."""


class QdrantStoreError(QdrantVectorStorageError):
    """Raised when Qdrant collection or point operations fail."""
