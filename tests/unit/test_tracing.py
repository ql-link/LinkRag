from __future__ import annotations

import uuid

from src.observability.tracing import (
    TRACE_ID_HEADER,
    extract_trace_id_from_headers,
    get_or_create_trace_id,
    get_trace_id,
    normalize_trace_id,
    trace_context,
)


def test_should_normalize_safe_trace_id():
    assert normalize_trace_id(" trace-123 ") == "trace-123"


def test_should_reject_invalid_trace_id():
    assert normalize_trace_id("trace\n123") is None
    assert normalize_trace_id("x" * 129) is None
    assert normalize_trace_id("") is None


def test_should_create_uuid_trace_id_when_missing():
    trace_id = get_or_create_trace_id(None)

    assert str(uuid.UUID(trace_id)) == trace_id


def test_should_extract_trace_id_from_case_insensitive_headers():
    assert extract_trace_id_from_headers({"x-trace-id": "abc-123"}) == "abc-123"
    assert extract_trace_id_from_headers({TRACE_ID_HEADER: "trace-456"}) == "trace-456"


def test_trace_context_should_reset_previous_value():
    assert get_trace_id() is None

    with trace_context("outer"):
        assert get_trace_id() == "outer"
        with trace_context("inner"):
            assert get_trace_id() == "inner"
        assert get_trace_id() == "outer"

    assert get_trace_id() is None
