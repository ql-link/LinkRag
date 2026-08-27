from __future__ import annotations

from unittest.mock import ANY, AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import TypeAdapter, ValidationError

from src.api.java_access_auth import AuthContext, verify_user_token
from src.api.routes import wiki
from src.api.schemas.wiki import WikiSearchResult
from src.application.recall_errors import RecallApiError
from src.application.wiki_runtime import get_wiki_runtime


def _app(runtime: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(wiki.router)
    app.dependency_overrides[verify_user_token] = lambda: AuthContext(
        user_id=7, request_id="req-wiki"
    )
    app.dependency_overrides[get_wiki_runtime] = lambda: runtime

    @app.exception_handler(RecallApiError)
    async def handle(_request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "data": None},
        )

    return app


def _empty_search_payload() -> dict:
    return {
        "results": [],
        "chunks": [],
        "failed_sources": [],
        "page_size": 15,
        "has_more": False,
    }


def _heading_summary() -> dict:
    """返回严格搜索联合类型复用的最小标题摘要。"""

    return {
        "heading_key": "a" * 64,
        "doc_id": 3,
        "dataset_id": 10,
        "title": "Guide",
        "heading_level": 1,
        "path": [],
        "direct_chunk_count": 0,
        "direct_chunks_has_more": False,
    }


@pytest.mark.asyncio
async def test_search_rejects_invalid_json_and_unknown_fields_before_runtime():
    runtime = AsyncMock()
    transport = ASGITransport(app=_app(runtime))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        invalid = await client.post(
            "/api/v1/wiki/search",
            content=b"{",
            headers={"content-type": "application/json"},
        )
        unknown = await client.post(
            "/api/v1/wiki/search",
            json={"query": "guide", "top_k": 100},
        )

    assert invalid.status_code == 422
    assert unknown.status_code == 422
    assert invalid.json()["code"] == "RECALL_INVALID_REQUEST"
    runtime.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_chunk_locations_preserves_manual_request_error_contract():
    """补充 OpenAPI 描述不能绕过既有的统一请求错误映射。"""

    runtime = AsyncMock()
    transport = ASGITransport(app=_app(runtime))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        invalid = await client.post(
            "/api/v1/wiki/chunk-locations",
            content=b"{",
            headers={"content-type": "application/json"},
        )
        unknown = await client.post(
            "/api/v1/wiki/chunk-locations",
            json={"chunk_ids": ["C1"], "unknown": True},
        )

    assert invalid.status_code == unknown.status_code == 422
    assert invalid.json()["code"] == unknown.json()["code"] == "RECALL_INVALID_REQUEST"
    runtime.locate_chunks.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_rejects_boolean_ids_before_runtime():
    runtime = AsyncMock()
    transport = ASGITransport(app=_app(runtime))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/wiki/search",
            content='{"query":"x","dataset_ids":[true]}',
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 422
    assert response.json()["code"] == "RECALL_INVALID_REQUEST"
    runtime.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_rejects_blank_query_before_runtime():
    runtime = AsyncMock()
    transport = ASGITransport(app=_app(runtime))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/wiki/search", json={"query": "  \n "})

    assert response.status_code == 400
    assert response.json()["code"] == "RECALL_INVALID_REQUEST"
    runtime.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_normalizes_id_arrays_and_returns_request_id():
    runtime = AsyncMock()
    runtime.search.return_value = _empty_search_payload()
    transport = ASGITransport(app=_app(runtime))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/wiki/search",
            json={"query": "Guide", "dataset_ids": [20, 10, 20], "doc_ids": [3, 2, 3]},
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-wiki"
    runtime.search.assert_awaited_once()
    kwargs = runtime.search.await_args.kwargs
    assert kwargs["dataset_ids"] == [10, 20]
    assert kwargs["doc_ids"] == [2, 3]


@pytest.mark.asyncio
async def test_search_keeps_union_null_fields_but_omits_absent_cursors():
    runtime = AsyncMock()
    runtime.search.return_value = {
        "results": [
            {
                "result_type": "HEADING",
                "source": "exact_title",
                "heading": {
                    "heading_key": "a" * 64,
                    "doc_id": 3,
                    "dataset_id": 10,
                    "title": "Guide",
                    "heading_level": 1,
                    "path": [],
                    "direct_chunk_count": 0,
                    "direct_chunks_has_more": False,
                },
                "chunk_id": None,
                "bm25_score": None,
            },
            {
                "result_type": "CHUNK",
                "source": "bm25",
                "heading": None,
                "chunk_id": "C1",
                "bm25_score": 1.0,
            },
        ],
        "chunks": [],
        "failed_sources": [],
        "page_size": 15,
        "has_more": False,
    }
    transport = ASGITransport(app=_app(runtime))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/wiki/search", json={"query": "Guide"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"][0]["chunk_id"] is None
    assert payload["results"][0]["bm25_score"] is None
    assert payload["results"][1]["heading"] is None
    assert "direct_chunk_preview_id" not in payload["results"][0]["heading"]
    assert "next_cursor" not in payload


@pytest.mark.parametrize(
    "payload",
    [
        {
            "result_type": "INVALID",
            "source": "anything",
            "heading": None,
            "chunk_id": None,
            "bm25_score": None,
        },
        {
            "result_type": "HEADING",
            "source": "bm25",
            "heading": _heading_summary(),
            "chunk_id": None,
            "bm25_score": None,
        },
        {
            "result_type": "HEADING",
            "source": "exact_title",
            "heading": _heading_summary(),
            "chunk_id": "C1",
            "bm25_score": None,
        },
        {
            "result_type": "HEADING",
            "source": "exact_title",
            "heading": _heading_summary(),
            "chunk_id": None,
            "bm25_score": 1.0,
        },
        {
            "result_type": "HEADING",
            "source": "exact_title",
            "chunk_id": None,
            "bm25_score": None,
        },
        {
            "result_type": "HEADING",
            "source": "exact_title",
            "heading": None,
            "chunk_id": None,
            "bm25_score": None,
        },
        {
            "result_type": "CHUNK",
            "source": "title_prefix",
            "heading": None,
            "chunk_id": "C1",
            "bm25_score": 1.0,
        },
        {
            "result_type": "CHUNK",
            "source": "bm25",
            "heading": _heading_summary(),
            "chunk_id": "C1",
            "bm25_score": 1.0,
        },
        {
            "result_type": "CHUNK",
            "source": "bm25",
            "heading": None,
            "chunk_id": None,
            "bm25_score": 1.0,
        },
        {
            "result_type": "CHUNK",
            "source": "bm25",
            "heading": None,
            "bm25_score": 1.0,
        },
        {
            "result_type": "CHUNK",
            "source": "bm25",
            "heading": None,
            "chunk_id": "C1",
        },
        {
            "result_type": "CHUNK",
            "source": "bm25",
            "heading": None,
            "chunk_id": "C1",
            "bm25_score": None,
        },
    ],
)
def test_search_result_discriminated_union_rejects_invalid_field_combinations(payload):
    with pytest.raises(ValidationError):
        TypeAdapter(WikiSearchResult).validate_python(payload)


def test_openapi_exposes_search_result_discriminator_and_two_branches():
    schemas = _app(AsyncMock()).openapi()["components"]["schemas"]
    result_items = schemas["WikiSearchResponse"]["properties"]["results"]["items"]

    assert result_items["discriminator"]["propertyName"] == "result_type"
    assert set(result_items["discriminator"]["mapping"]) == {"HEADING", "CHUNK"}
    assert {item["$ref"].rsplit("/", 1)[-1] for item in result_items["oneOf"]} == {
        "WikiHeadingSearchResult",
        "WikiChunkSearchResult",
    }
    required_fields = {"result_type", "source", "heading", "chunk_id", "bm25_score"}
    assert set(schemas["WikiHeadingSearchResult"]["required"]) == required_fields
    assert set(schemas["WikiChunkSearchResult"]["required"]) == required_fields


def test_openapi_exposes_required_request_bodies_for_manual_parsers():
    """手工解析请求体时也必须把既有 Pydantic 契约暴露给 OpenAPI。"""

    paths = _app(AsyncMock()).openapi()["paths"]
    cases = {
        "/api/v1/wiki/search": (
            {"query", "dataset_ids", "doc_ids", "cursor"},
            {"query"},
        ),
        "/api/v1/wiki/chunk-locations": (
            {"chunk_ids", "dataset_ids"},
            {"chunk_ids"},
        ),
    }

    for path, (properties, required) in cases.items():
        request_body = paths[path]["post"]["requestBody"]
        schema = request_body["content"]["application/json"]["schema"]

        assert request_body["required"] is True
        assert set(schema["properties"]) == properties
        assert set(schema["required"]) == required
        assert schema["additionalProperties"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_result",
    [
        {
            "result_type": "HEADING",
            "source": "exact_title",
            "chunk_id": None,
            "bm25_score": None,
        },
        {
            "result_type": "CHUNK",
            "source": "bm25",
            "heading": None,
            "chunk_id": "C1",
        },
    ],
)
async def test_search_route_rejects_invalid_runtime_result(invalid_result):
    """HTTP 路由必须以响应 Schema 拒绝 Runtime 返回的缺字段结果。"""

    runtime = AsyncMock()
    runtime.search.return_value = {
        **_empty_search_payload(),
        "results": [invalid_result],
    }
    transport = ASGITransport(app=_app(runtime))

    with pytest.raises(ValidationError):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/v1/wiki/search", json={"query": "Guide"})


@pytest.mark.asyncio
async def test_heading_expansion_location_and_tree_routes():
    runtime = AsyncMock()
    runtime.expand_heading_chunks.return_value = {
        "doc_id": 3,
        "heading_key": "a" * 64,
        "chunks": [],
        "page_size": 15,
        "direct_chunks_has_more": False,
    }
    runtime.locate_chunks.return_value = {
        "locations": [{"chunk_id": "c1", "doc_id": 3, "dataset_id": 10, "positions": []}]
    }
    runtime.get_document_tree.return_value = {
        "doc_id": 3,
        "dataset_id": 10,
        "original_filename": "guide.md",
        "headings": [],
        "root_chunk_ids": [],
        "chunks": [],
    }
    transport = ASGITransport(app=_app(runtime))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        expanded = await client.get(f"/api/v1/wiki/documents/3/headings/{'a' * 64}/chunks")
        located = await client.post(
            "/api/v1/wiki/chunk-locations",
            json={"chunk_ids": ["c1", "c1"], "dataset_ids": [10]},
        )
        tree = await client.get("/api/v1/wiki/documents/3/tree")

    assert expanded.status_code == located.status_code == tree.status_code == 200
    assert located.json()["locations"][0]["chunk_id"] == "c1"
    runtime.locate_chunks.assert_awaited_once_with(
        ANY,
        chunk_ids=["c1"],
        dataset_ids=[10],
    )


@pytest.mark.asyncio
async def test_heading_route_rejects_invalid_path_before_runtime():
    runtime = AsyncMock()
    transport = ASGITransport(app=_app(runtime))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/wiki/documents/0/headings/not-a-key/chunks")

    assert response.status_code == 422
    runtime.expand_heading_chunks.assert_not_awaited()
