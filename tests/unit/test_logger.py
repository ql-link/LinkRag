from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.config import settings
from src.observability.logging import (
    _PROJECT_ROOT,
    _resolve_log_dir,
    _service_name,
    fingerprint_log_value,
    logger,
    safe_exception_stack,
    sanitize_url_for_log,
    setup_logger,
    truncate_log_value,
)
from src.observability.tracing import trace_context


def test_should_resolve_relative_log_dir_from_project_root():
    assert _resolve_log_dir("logs") == _PROJECT_ROOT / "logs"


def test_should_keep_absolute_log_dir():
    absolute = Path("/tmp/tolink-rag-logs")

    assert _resolve_log_dir(str(absolute)) == absolute


def test_should_fallback_empty_log_dir_to_project_logs():
    assert _resolve_log_dir(" ") == _PROJECT_ROOT / "logs"


def test_should_use_tolink_rag_as_default_service_name():
    original = settings.LOG_SERVICE_NAME
    settings.LOG_SERVICE_NAME = ""

    try:
        assert _service_name() == "tolink-rag"
    finally:
        settings.LOG_SERVICE_NAME = original


def test_should_allow_explicit_log_service_name_override():
    original = settings.LOG_SERVICE_NAME
    settings.LOG_SERVICE_NAME = "unit-service"

    try:
        assert _service_name() == "unit-service"
    finally:
        settings.LOG_SERVICE_NAME = original


def test_sanitize_url_removes_credentials_query_and_fragment():
    sanitized = sanitize_url_for_log(
        "amqp://admin:super-secret@mq.internal:5672/vhost?token=hidden#fragment"
    )

    assert sanitized == "amqp://<redacted>@mq.internal:5672/vhost"
    assert "super-secret" not in sanitized
    assert "token" not in sanitized
    assert "hidden" not in sanitized


def test_truncate_log_value_flattens_and_limits_external_text():
    value = "first line\nsecond line " + "x" * 100

    result = truncate_log_value(value, 32)

    assert "\n" not in result
    assert result.startswith("first line second line")
    assert "truncated,total_chars=" in result


def test_truncate_log_value_redacts_common_secret_forms():
    value = (
        "amqp://user:password@mq.internal/vhost "
        'api_key="sk-secret" Authorization=Bearer abc.def.ghi signature=qwerty'
    )

    result = truncate_log_value(value)

    assert "password" not in result
    assert "sk-secret" not in result
    assert "abc.def.ghi" not in result
    assert "qwerty" not in result
    assert result.count("<redacted>") >= 4


def test_fingerprint_log_value_is_stable_without_exposing_input():
    secret_url = "https://storage.example/file.png?signature=secret"

    first = fingerprint_log_value(secret_url)
    second = fingerprint_log_value(secret_url)

    assert first == second
    assert len(first) == 12
    assert "secret" not in first


def test_safe_exception_stack_keeps_frames_without_secret_message():
    try:
        raise RuntimeError("api_key=sk-should-not-appear")
    except RuntimeError as exc:
        stack = safe_exception_stack(exc)

    assert "test_safe_exception_stack" in stack
    assert "sk-should-not-appear" not in stack


@pytest.mark.asyncio
async def test_file_sink_should_write_json_record_with_trace_fields(tmp_path):
    original_values = {
        "LOG_FILE_ENABLED": settings.LOG_FILE_ENABLED,
        "LOG_DIR": settings.LOG_DIR,
        "LOG_SERVICE_NAME": settings.LOG_SERVICE_NAME,
        "LOG_LEVEL": settings.LOG_LEVEL,
        "LOG_RETENTION_DAYS": settings.LOG_RETENTION_DAYS,
    }
    settings.LOG_FILE_ENABLED = True
    settings.LOG_DIR = str(tmp_path)
    settings.LOG_SERVICE_NAME = "unit-service"
    settings.LOG_LEVEL = "INFO"
    settings.LOG_RETENTION_DAYS = 7

    try:
        setup_logger()
        with trace_context("trace-unit-1"):
            logger.info("json trace probe")
        await logger.complete()

        log_files = [
            path for path in tmp_path.rglob("unit-service-*.log") if "-error-" not in path.name
        ]
        assert len(log_files) == 1

        payload = json.loads(log_files[0].read_text(encoding="utf-8").splitlines()[-1])
        record = payload["record"]
        extra = record["extra"]

        assert record["message"] == "json trace probe"
        assert record["level"]["name"] == "INFO"
        assert extra["service"] == "unit-service"
        assert extra["trace_id"] == "trace-unit-1"
        assert extra["pid"] == os.getpid()
        assert extra["host"]
        assert extra["logger_name"]
    finally:
        for name, value in original_values.items():
            setattr(settings, name, value)
        setup_logger()
