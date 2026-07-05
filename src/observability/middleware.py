from __future__ import annotations

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.observability.tracing import (
    TRACE_ID_HEADER,
    get_or_create_trace_id,
    reset_trace_id,
    set_trace_id,
)


class TraceContextMiddleware:
    """Bind X-Trace-Id to the current request context and echo it in responses."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_headers = Headers(scope=scope)
        trace_id = get_or_create_trace_id(request_headers.get(TRACE_ID_HEADER))
        token = set_trace_id(trace_id)

        async def send_with_trace_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers[TRACE_ID_HEADER] = trace_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace_id)
        finally:
            reset_trace_id(token)
