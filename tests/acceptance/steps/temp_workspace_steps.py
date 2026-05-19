"""``temp_workspace`` 启动清理 step。"""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import given, parsers, then, when

from src.config import settings
from src.core.pipeline.parse_task import temp_workspace


@given(parsers.re(r'PARSE_TEMP_DIR 在启动前包含残留文件 \[(?P<files>[^\]]+)\]'))
def _given_residual_files(state, files):
    temp_dir = Path(settings.PARSE_TEMP_DIR)
    temp_dir.mkdir(parents=True, exist_ok=True)
    # files 形如 ``"abc.tmp", "def.tmp"``；用 ast.literal_eval 解析。
    import ast

    names = ast.literal_eval(f"[{files}]")
    for name in names:
        (temp_dir / name).write_bytes(b"leftover")
    state._startup_dir = temp_dir


@given("PARSE_TEMP_DIR 路径在启动前不存在")
def _given_dir_missing(state, tmp_path, monkeypatch):
    missing = tmp_path / "absent" / "parse-tmp"
    if missing.exists():
        for child in missing.iterdir():
            child.unlink()
        missing.rmdir()
    monkeypatch.setattr(settings, "PARSE_TEMP_DIR", str(missing))
    state._startup_dir = missing
    assert not missing.exists()


@when("worker 进程启动")
def _when_worker_starts(state):
    state._startup_error = None
    try:
        temp_workspace.ensure_clean_on_startup(Path(settings.PARSE_TEMP_DIR))
    except BaseException as exc:  # noqa: BLE001
        state._startup_error = exc


@then("PARSE_TEMP_DIR 存在")
def _then_dir_exists(state):
    assert Path(settings.PARSE_TEMP_DIR).is_dir()


@then(parsers.re(r"PARSE_TEMP_DIR 内文件数 == (?P<count>\d+)"))
def _then_dir_file_count(state, count):
    n = int(count)
    files = [p for p in Path(settings.PARSE_TEMP_DIR).iterdir() if p.is_file()]
    assert len(files) == n, f"期望文件数 {n}，实际 {files}"


@then("PARSE_TEMP_DIR 被创建为空目录")
def _then_dir_created_empty(state):
    p = Path(settings.PARSE_TEMP_DIR)
    assert p.is_dir()
    assert [c for c in p.iterdir() if c.is_file()] == []


@then("worker 启动成功不抛错")
def _then_no_startup_error(state):
    assert state.__dict__.get("_startup_error") is None
