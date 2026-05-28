from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.es_index_storage import (
    Bm25RecallRequest,
    EsBm25Retriever,
    EsRecallValidationError,
    EsRetrievalError,
)


def build_request(**overrides) -> Bm25RecallRequest:
    base = dict(
        user_id=20,
        dataset_id=30,
        doc_id=None,
        tokens=["合同", "付款"],
        top_k=5,
    )
    base.update(overrides)
    return Bm25RecallRequest(**base)


def build_client(response: dict | None = None) -> MagicMock:
    client = MagicMock()
    client.search = AsyncMock(return_value=response or {"hits": {"hits": []}})
    return client


def build_retriever(client: MagicMock) -> EsBm25Retriever:
    return EsBm25Retriever(client_factory=lambda: client, index_name="idx")


def get_search_kwargs(client: MagicMock) -> dict:
    return client.search.await_args.kwargs


def get_bool_query(client: MagicMock) -> dict:
    return get_search_kwargs(client)["query"]["bool"]


def get_multi_match(client: MagicMock) -> dict:
    return get_bool_query(client)["must"][0]["multi_match"]


class TestEsBm25Retriever:
    async def test_should_return_hits_with_scores_in_es_order(self):
        client = build_client(
            {
                "hits": {
                    "hits": [
                        {"_source": {"chunk_id": "c-2", "doc_id": 200}, "_score": 7.5},
                        {"_source": {"chunk_id": "c-1", "doc_id": 100}, "_score": 6.25},
                    ]
                }
            }
        )
        retriever = build_retriever(client)

        hits = await retriever.recall_topk_chunks(build_request())

        assert [hit.chunk_id for hit in hits] == ["c-2", "c-1"]
        assert [hit.doc_id for hit in hits] == [200, 100]
        assert [hit.score for hit in hits] == [7.5, 6.25]
        assert not hasattr(hits[0], "content")

    @pytest.mark.parametrize("top_k", [1, 3, 10])
    async def test_should_pass_top_k_as_search_size(self, top_k):
        client = build_client()
        retriever = build_retriever(client)

        await retriever.recall_topk_chunks(build_request(top_k=top_k))

        assert get_search_kwargs(client)["size"] == top_k

    async def test_should_use_raw_es_score_without_normalization(self):
        client = build_client(
            {"hits": {"hits": [{"_source": {"chunk_id": "c-1", "doc_id": 100}, "_score": 123.456}]}}
        )
        retriever = build_retriever(client)

        hits = await retriever.recall_topk_chunks(build_request())

        assert hits[0].score == 123.456

    async def test_should_query_weighted_coarse_and_fine_token_fields(self):
        client = build_client()
        retriever = build_retriever(client)

        await retriever.recall_topk_chunks(build_request())

        multi_match = get_multi_match(client)
        assert multi_match["fields"] == ["coarse_tokens^2", "fine_tokens"]
        assert multi_match["type"] == "best_fields"

    async def test_should_filter_by_user_and_dataset(self):
        client = build_client()
        retriever = build_retriever(client)

        await retriever.recall_topk_chunks(build_request(user_id=20, dataset_id=30))

        filters = get_bool_query(client)["filter"]
        assert {"term": {"user_id": 20}} in filters
        assert {"term": {"dataset_id": 30}} in filters

    async def test_should_use_dataset_id_as_routing(self):
        client = build_client()
        retriever = build_retriever(client)

        await retriever.recall_topk_chunks(build_request(dataset_id=30))

        assert get_search_kwargs(client)["routing"] == "30"

    async def test_should_include_doc_id_filter_when_provided(self):
        client = build_client()
        retriever = build_retriever(client)

        await retriever.recall_topk_chunks(build_request(doc_id=10))

        assert {"term": {"doc_id": 10}} in get_bool_query(client)["filter"]

    async def test_should_not_include_doc_id_filter_when_missing(self):
        client = build_client()
        retriever = build_retriever(client)

        await retriever.recall_topk_chunks(build_request(doc_id=None))

        filters = get_bool_query(client)["filter"]
        assert all("doc_id" not in item.get("term", {}) for item in filters)

    async def test_should_request_only_chunk_id_source(self):
        client = build_client()
        retriever = build_retriever(client)

        await retriever.recall_topk_chunks(build_request())

        assert get_search_kwargs(client)["_source"] == ["chunk_id", "doc_id"]

    async def test_should_return_empty_without_es_for_empty_tokens(self):
        client = build_client()
        retriever = build_retriever(client)

        hits = await retriever.recall_topk_chunks(build_request(tokens=[]))

        assert hits == []
        client.search.assert_not_awaited()

    async def test_should_return_empty_without_es_for_blank_tokens(self):
        client = build_client()
        retriever = build_retriever(client)

        hits = await retriever.recall_topk_chunks(build_request(tokens=[" ", "\t"]))

        assert hits == []
        client.search.assert_not_awaited()

    async def test_should_return_empty_when_es_hits_empty(self):
        client = build_client({"hits": {"hits": []}})
        retriever = build_retriever(client)

        hits = await retriever.recall_topk_chunks(build_request())

        assert hits == []

    @pytest.mark.parametrize("top_k", [0, -1])
    async def test_should_raise_validation_error_for_non_positive_top_k(self, top_k):
        client = build_client()
        retriever = build_retriever(client)

        with pytest.raises(EsRecallValidationError):
            await retriever.recall_topk_chunks(build_request(top_k=top_k))

        client.search.assert_not_awaited()

    @pytest.mark.parametrize(
        "overrides",
        [
            {"user_id": None},
            {"user_id": 0},
            {"dataset_id": None},
            {"dataset_id": 0},
        ],
    )
    async def test_should_raise_validation_error_when_owner_missing(self, overrides):
        client = build_client()
        retriever = build_retriever(client)

        with pytest.raises(EsRecallValidationError):
            await retriever.recall_topk_chunks(build_request(**overrides))

        client.search.assert_not_awaited()

    async def test_should_wrap_es_search_failure(self):
        client = build_client()
        client.search = AsyncMock(side_effect=RuntimeError("es down"))
        retriever = build_retriever(client)

        with pytest.raises(EsRetrievalError) as exc_info:
            await retriever.recall_topk_chunks(build_request())

        assert "es_retrieval:" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, RuntimeError)
