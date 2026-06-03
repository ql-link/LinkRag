"""Elasticsearch index mapping for chunk token documents."""

from __future__ import annotations


def build_es_index_body(*, shards: int, replicas: int) -> dict[str, object]:
    """Build the index settings and mappings used by the ES indexing stage."""

    return {
        "settings": {
            "number_of_shards": shards,
            "number_of_replicas": replicas,
            "analysis": {
                "analyzer": {
                    "chunk_index_analyzer": {
                        "type": "custom",
                        "tokenizer": "whitespace",
                        "filter": ["lowercase"],
                    },
                    "chunk_search_analyzer": {
                        "type": "custom",
                        "tokenizer": "whitespace",
                        "filter": ["lowercase"],
                    },
                }
            },
        },
        "mappings": {
            "_source": {"excludes": ["coarse_tokens", "fine_tokens"]},
            "routing": {"required": True},
            "properties": {
                "chunk_id": {"type": "keyword"},
                "user_id": {"type": "long"},
                "dataset_id": {"type": "long"},
                "doc_id": {"type": "long"},
                "task_id": {"type": "keyword"},
                "chunk_index": {"type": "integer"},
                "coarse_tokens": {
                    "type": "text",
                    "analyzer": "chunk_index_analyzer",
                    "search_analyzer": "chunk_search_analyzer",
                    "store": False,
                },
                "fine_tokens": {
                    "type": "text",
                    "analyzer": "chunk_index_analyzer",
                    "search_analyzer": "chunk_search_analyzer",
                    "store": False,
                },
            },
        },
    }
