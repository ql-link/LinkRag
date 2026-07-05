from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.observability.middleware import TraceContextMiddleware
from src.observability.tracing import TRACE_ID_HEADER, get_trace_id


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/probe")
    async def probe():
        return {"trace_id": get_trace_id()}

    app.add_middleware(TraceContextMiddleware)
    return app


@pytest.mark.asyncio
async def test_should_reuse_request_trace_id_and_echo_response_header():
    transport = ASGITransport(app=_build_app())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/probe", headers={TRACE_ID_HEADER: "trace-http-1"})

    assert response.status_code == 200
    assert response.headers[TRACE_ID_HEADER] == "trace-http-1"
    assert response.json() == {"trace_id": "trace-http-1"}
    assert get_trace_id() is None


@pytest.mark.asyncio
async def test_should_generate_trace_id_when_request_header_missing():
    transport = ASGITransport(app=_build_app())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/probe")

    trace_id = response.headers[TRACE_ID_HEADER]
    assert str(uuid.UUID(trace_id)) == trace_id
    assert response.json() == {"trace_id": trace_id}
    assert get_trace_id() is None
