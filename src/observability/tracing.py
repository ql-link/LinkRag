from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator, Mapping, Optional

TRACE_ID_HEADER = "X-Trace-Id"

_TRACE_ID_VAR: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)
_TRACE_ID_MAX_LENGTH = 128
_TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:/@+-]+$")
_TRACE_ID_HEADER_ALIASES = (
    TRACE_ID_HEADER,
    "x-trace-id",
    "trace_id",
    "trace-id",
)


def new_trace_id() -> str:
    """Create a request-level trace id for inbound requests without one."""
    return str(uuid.uuid4())


def normalize_trace_id(raw: object) -> str | None:
    """Return a safe trace id value, or None when the input is absent/invalid."""
    if raw is None:
        return None

    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None

    value = str(raw).strip()
    if not value or len(value) > _TRACE_ID_MAX_LENGTH:
        return None
    if not _TRACE_ID_PATTERN.fullmatch(value):
        return None
    return value


def get_or_create_trace_id(raw: object) -> str:
    return normalize_trace_id(raw) or new_trace_id()


def get_trace_id() -> str | None:
    return _TRACE_ID_VAR.get()


def set_trace_id(trace_id: str | None) -> Token[Optional[str]]:
    return _TRACE_ID_VAR.set(normalize_trace_id(trace_id))


def reset_trace_id(token: Token[Optional[str]]) -> None:
    _TRACE_ID_VAR.reset(token)


@contextmanager
def trace_context(trace_id: str | None) -> Iterator[None]:
    token = set_trace_id(trace_id)
    try:
        yield
    finally:
        reset_trace_id(token)


def extract_trace_id_from_headers(headers: Mapping[str, object] | None) -> str | None:
    if not headers:
        return None

    normalized_headers = {str(key).lower(): value for key, value in headers.items()}
    for header_name in _TRACE_ID_HEADER_ALIASES:
        trace_id = normalize_trace_id(normalized_headers.get(header_name.lower()))
        if trace_id:
            return trace_id
    return None


def extract_trace_id_from_metadata(metadata: Mapping[str, object] | None) -> str | None:
    if not metadata:
        return None

    headers = metadata.get("headers")
    if isinstance(headers, Mapping):
        trace_id = extract_trace_id_from_headers(headers)
        if trace_id:
            return trace_id

    return extract_trace_id_from_headers(metadata)
