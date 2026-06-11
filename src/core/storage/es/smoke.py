"""Minimal ES keyword query smoke helpers for integration tests."""

from __future__ import annotations

from elasticsearch import AsyncElasticsearch


async def run_es_index_smoke(
    *,
    client: AsyncElasticsearch,
    index_name: str,
    dataset_id: int,
    token: str,
    expected_chunk_id: str,
    field: str = "coarse_tokens",
) -> bool:
    """Return whether a token query can locate the expected chunk id."""

    response = await client.search(
        index=index_name,
        routing=str(dataset_id),
        query={"match": {field: token}},
        _source=["chunk_id", "doc_id", "dataset_id", "user_id", "task_id", "chunk_index"],
    )
    hits = response.get("hits", {}).get("hits", [])
    return any(hit.get("_source", {}).get("chunk_id") == expected_chunk_id for hit in hits)
