class ChunkFactStorageError(Exception):
    """Base error for SQL fact storage operations."""


class ChunkRepositoryError(ChunkFactStorageError):
    """Raised when chunk fact repository operations fail."""
