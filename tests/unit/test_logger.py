from __future__ import annotations

from pathlib import Path

from src.utils.logger import _PROJECT_ROOT, _resolve_log_dir


def test_should_resolve_relative_log_dir_from_project_root():
    assert _resolve_log_dir("logs") == _PROJECT_ROOT / "logs"


def test_should_keep_absolute_log_dir():
    absolute = Path("/tmp/tolink-rag-logs")

    assert _resolve_log_dir(str(absolute)) == absolute


def test_should_fallback_empty_log_dir_to_project_logs():
    assert _resolve_log_dir(" ") == _PROJECT_ROOT / "logs"
