"""Exceptions raised by ES index storage."""

from __future__ import annotations


class EsIndexingError(Exception):
    """Base class for ES indexing errors."""


class EsDocumentValidationError(EsIndexingError):
    """Raised when a chunk cannot be converted into a valid ES document."""

    def __init__(self, chunk_id: str, message: str) -> None:
        self.chunk_id = chunk_id
        super().__init__(message if message.startswith("validation:") else f"validation: {message}")


class EsBulkError(EsIndexingError):
    """Raised when ES service-level operations fail."""

    def __init__(self, message: str) -> None:
        super().__init__(message if message.startswith("es_bulk:") else f"es_bulk: {message}")


class EsRecallValidationError(ValueError):
    """Raised when an ES recall request is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message
            if message.startswith("es_recall_validation:")
            else f"es_recall_validation: {message}"
        )


class EsRetrievalError(Exception):
    """Raised when ES retrieval fails."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message if message.startswith("es_retrieval:") else f"es_retrieval: {message}"
        )
