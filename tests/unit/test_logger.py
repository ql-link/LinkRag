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
    logger,
    setup_logger,
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
