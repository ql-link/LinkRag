"""``temp_workspace`` 内部边界单测。

acceptance.feature 中已经覆盖"启动清理两条 Scenario"，本文件补充 acceptance 不便表
达的内部行为：``safe_unlink`` 的幂等性、``create_temp_file`` 的命名格式。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.pipeline.parse_task import temp_workspace


def test_safe_unlink_none_is_noop():
    # finally 兜底常常拿到 None；不应抛错。
    temp_workspace.safe_unlink(None)


def test_safe_unlink_missing_path_is_noop(tmp_path):
    target = tmp_path / "absent.tmp"
    assert not target.exists()
    # 早删 + finally 兜底两次都会调到 safe_unlink；第二次必须幂等。
    temp_workspace.safe_unlink(target)
    temp_workspace.safe_unlink(target)


def test_safe_unlink_existing_file(tmp_path):
    target = tmp_path / "exists.tmp"
    target.write_bytes(b"x")
    temp_workspace.safe_unlink(target)
    assert not target.exists()


def test_create_temp_file_name_pattern(tmp_path):
    p = temp_workspace.create_temp_file("task-A", tmp_path)
    assert p.parent == tmp_path
    name = p.name
    # 命名格式 ``parse-{task_id}-{8-hex}.tmp``
    assert name.startswith("parse-task-A-")
    assert name.endswith(".tmp")
    rand_part = name[len("parse-task-A-") : -len(".tmp")]
    assert len(rand_part) == 8
    int(rand_part, 16)  # 必须是合法 hex


def test_create_temp_file_collision_uses_random_suffix(tmp_path):
    a = temp_workspace.create_temp_file("dup", tmp_path)
    b = temp_workspace.create_temp_file("dup", tmp_path)
    assert a != b, "同 task_id 两次调用应通过随机 hex 后缀区分"


def test_ensure_clean_on_startup_creates_missing(tmp_path):
    missing = tmp_path / "absent" / "parse-tmp"
    assert not missing.exists()
    temp_workspace.ensure_clean_on_startup(missing)
    assert missing.is_dir()


def test_ensure_clean_on_startup_removes_residue(tmp_path):
    (tmp_path / "a.tmp").write_bytes(b"1")
    (tmp_path / "b.tmp").write_bytes(b"2")
    temp_workspace.ensure_clean_on_startup(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_ensure_clean_on_startup_preserves_subdirectory(tmp_path):
    # 子目录不递归删除：保留下来供人工排查异常残留。
    sub = tmp_path / "manual-debug"
    sub.mkdir()
    (sub / "leftover").write_bytes(b"keep")
    (tmp_path / "top.tmp").write_bytes(b"1")
    temp_workspace.ensure_clean_on_startup(tmp_path)
    assert sub.exists()
    assert (sub / "leftover").exists()
    assert not (tmp_path / "top.tmp").exists()
