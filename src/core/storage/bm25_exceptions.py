"""BM25 召回的后端无关异常。"""

from __future__ import annotations


class Bm25RecallValidationError(ValueError):
    """BM25 召回请求参数不合法。"""

    def __init__(self, message: str) -> None:
        super().__init__(
            message
            if message.startswith("bm25_recall_validation:")
            else f"bm25_recall_validation: {message}"
        )


class Bm25RetrievalError(Exception):
    """BM25 后端查询失败。"""

    def __init__(self, message: str) -> None:
        super().__init__(
            message if message.startswith("bm25_retrieval:") else f"bm25_retrieval: {message}"
        )
