"""BM25 chunk retrieval backed by Elasticsearch token indexes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from elasticsearch import AsyncElasticsearch

from src.config import settings

from .client import get_async_es_client
from .exceptions import EsRecallValidationError, EsRetrievalError
from .retrieval_models import Bm25ChunkHit, Bm25RecallRequest

ClientFactory = Callable[[], AsyncElasticsearch | Awaitable[AsyncElasticsearch]]


class EsBm25Retriever:
    """Recall topK chunk ids by BM25 over pre-tokenized ES fields."""

    def __init__(
        self,
        *,
        client_factory: ClientFactory | None = None,
        index_name: str | None = None,
    ) -> None:
        self._client_factory = client_factory or (lambda: get_async_es_client(settings))
        self._index_name = index_name or settings.ES_INDEX_NAME

    async def recall_topk_chunks(self, request: Bm25RecallRequest) -> list[Bm25ChunkHit]:
        """Return BM25-ranked chunk ids and raw ES scores for one recall request."""

        self._validate_request(request)
        tokens = self._normalize_tokens(request.tokens)
        if not tokens:
            return []

        query = self._build_query(request, tokens)
        try:
            client = await self._resolve_client()
            response = await client.search(
                index=self._index_name,
                routing=str(request.dataset_id),
                size=request.top_k,
                query=query,
                _source=["chunk_id", "doc_id"],
                request_timeout=settings.ES_BULK_REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            raise EsRetrievalError(f"search failed - {exc}") from exc

        return self._extract_hits(response)

    async def _resolve_client(self) -> AsyncElasticsearch:
        client = self._client_factory()
        if hasattr(client, "__await__"):
            return await client  # type: ignore[no-any-return]
        return client  # type: ignore[return-value]

    @staticmethod
    def _normalize_tokens(tokens: Sequence[str]) -> list[str]:
        return [normalized for token in tokens if (normalized := str(token).strip())]

    @staticmethod
    def _validate_request(request: Bm25RecallRequest) -> None:
        if request.top_k is None or request.top_k <= 0:
            raise EsRecallValidationError("top_k must be positive")
        if request.user_id is None or request.user_id <= 0:
            raise EsRecallValidationError("user_id must be positive")
        if request.dataset_id is None or request.dataset_id <= 0:
            raise EsRecallValidationError("dataset_id must be positive")
        if request.tokens is None:
            raise EsRecallValidationError("tokens are required")

    @staticmethod
    def _build_query(request: Bm25RecallRequest, tokens: Sequence[str]) -> dict[str, Any]:
        filters: list[dict[str, Any]] = [
            {"term": {"user_id": request.user_id}},
            {"term": {"dataset_id": request.dataset_id}},
        ]
        if request.doc_id is not None:
            filters.append({"term": {"doc_id": request.doc_id}})

        return {
            "bool": {
                "filter": filters,
                "must": [
                    {
                        "multi_match": {
                            "fields": ["coarse_tokens^2", "fine_tokens"],
                            "query": " ".join(tokens),
                            "type": "best_fields",
                        }
                    }
                ],
            }
        }

    @staticmethod
    def _extract_hits(response: dict[str, Any]) -> list[Bm25ChunkHit]:
        hits = response.get("hits", {}).get("hits", [])
        results: list[Bm25ChunkHit] = []
        for hit in hits:
            source = hit.get("_source") or {}
            chunk_id = source.get("chunk_id")
            doc_id = source.get("doc_id")
            if not chunk_id or doc_id is None:
                continue
            results.append(
                Bm25ChunkHit(
                    chunk_id=str(chunk_id),
                    doc_id=int(doc_id),
                    score=float(hit.get("_score") or 0.0),
                )
            )
        return results
