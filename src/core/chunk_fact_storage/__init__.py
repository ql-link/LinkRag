from .constants import (
    CHUNK_DELETE_ALLOWED_STATUSES,
    CHUNK_DELETE_PROTECTED_STATUSES,
    CHUNK_DELETE_RETRY_STATUSES,
    CHUNK_STATUS_DELETED,
    CHUNK_STATUS_DELETE_FAILED,
    CHUNK_STATUS_DELETING,
    CHUNK_STATUS_FAILED,
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_INDEXING,
    CHUNK_STATUS_PENDING,
    CHUNK_UPDATE_ALLOWED_STATUSES,
    ES_STATUS_FAILED,
    ES_STATUS_PENDING,
    ES_STATUS_SUCCESS,
    MAX_ERROR_MSG_LENGTH,
)
__all__ = [
    "CHUNK_DELETE_ALLOWED_STATUSES",
    "CHUNK_DELETE_PROTECTED_STATUSES",
    "CHUNK_DELETE_RETRY_STATUSES",
    "CHUNK_STATUS_DELETED",
    "CHUNK_STATUS_DELETE_FAILED",
    "CHUNK_STATUS_DELETING",
    "CHUNK_STATUS_FAILED",
    "CHUNK_STATUS_INDEXED",
    "CHUNK_STATUS_INDEXING",
    "CHUNK_STATUS_PENDING",
    "CHUNK_UPDATE_ALLOWED_STATUSES",
    "ChunkPostStatus",
    "ChunkFactStorageError",
    "ChunkRepository",
    "ChunkRepositoryError",
    "ES_STATUS_FAILED",
    "ES_STATUS_PENDING",
    "ES_STATUS_SUCCESS",
    "FactChunkDraft",
    "MAX_ERROR_MSG_LENGTH",
    "decide_chunk_post_status",
]


def __getattr__(name: str):
    if name in {"FactChunkDraft", "ChunkPostStatus", "decide_chunk_post_status"}:
        from .models import ChunkPostStatus, FactChunkDraft, decide_chunk_post_status

        return {
            "FactChunkDraft": FactChunkDraft,
            "ChunkPostStatus": ChunkPostStatus,
            "decide_chunk_post_status": decide_chunk_post_status,
        }[name]
    if name == "ChunkRepository":
        from .repository import ChunkRepository

        return ChunkRepository
    if name in {"ChunkFactStorageError", "ChunkRepositoryError"}:
        from .exceptions import ChunkFactStorageError, ChunkRepositoryError

        return {
            "ChunkFactStorageError": ChunkFactStorageError,
            "ChunkRepositoryError": ChunkRepositoryError,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
