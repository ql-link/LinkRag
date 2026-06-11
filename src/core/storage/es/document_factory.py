"""Build ES bulk actions from preprocessed chunk token plans."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.core.preprocessor.models import ChunkWithTokens, FileIndexMeta

from .exceptions import EsDocumentValidationError


@dataclass(frozen=True, slots=True)
class EsBulkAction:
    """One chunk index operation prepared for the ES bulk API."""

    chunk_id: str
    operation: dict[str, Any]
    document: dict[str, Any]
    estimated_bytes: int


class EsDocumentFactory:
    """Construct thin ES documents that contain only tokens and locator fields."""

    def __init__(self, *, max_document_bytes: int) -> None:
        self._max_document_bytes = max_document_bytes

    def build_action(self, file_meta: FileIndexMeta, chunk: ChunkWithTokens) -> EsBulkAction:
        """Build one bulk index operation for a chunk token payload."""

        self._validate_chunk(chunk)
        document = {
            "chunk_id": chunk.chunk_id,
            "user_id": file_meta.user_id,
            "dataset_id": file_meta.dataset_id,
            "doc_id": file_meta.doc_id,
            "task_id": file_meta.task_id,
            "chunk_index": chunk.chunk_index,
            "coarse_tokens": chunk.coarse_tokens,
            "fine_tokens": chunk.fine_tokens,
        }
        document_id = (
            f"{file_meta.user_id}-{file_meta.dataset_id}-{file_meta.doc_id}-{chunk.chunk_id}"
        )
        operation = {"index": {"_id": document_id, "routing": str(file_meta.dataset_id)}}
        estimated_bytes = self._estimate_bytes(operation, document)
        if estimated_bytes > self._max_document_bytes:
            raise EsDocumentValidationError(
                chunk.chunk_id,
                f"document too large: {estimated_bytes} bytes",
            )
        return EsBulkAction(
            chunk_id=chunk.chunk_id,
            operation=operation,
            document=document,
            estimated_bytes=estimated_bytes,
        )

    @staticmethod
    def _validate_chunk(chunk: ChunkWithTokens) -> None:
        if not chunk.chunk_id:
            raise EsDocumentValidationError("", "chunk_id is required")
        if chunk.chunk_index is None or chunk.chunk_index < 0:
            raise EsDocumentValidationError(chunk.chunk_id, "chunk_index must be non-negative")
        if not isinstance(chunk.coarse_tokens, str) or not chunk.coarse_tokens.strip():
            raise EsDocumentValidationError(chunk.chunk_id, "coarse_tokens must be non-empty text")
        if not isinstance(chunk.fine_tokens, str) or not chunk.fine_tokens.strip():
            raise EsDocumentValidationError(chunk.chunk_id, "fine_tokens must be non-empty text")

    @staticmethod
    def _estimate_bytes(operation: dict[str, Any], document: dict[str, Any]) -> int:
        return len(json.dumps(operation, ensure_ascii=False).encode("utf-8")) + len(
            json.dumps(document, ensure_ascii=False).encode("utf-8")
        )
