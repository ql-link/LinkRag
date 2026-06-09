"""promote_acceptance.py 单元测试。

把模块的目录常量重定向到 tmp_path,并把对 check_acceptance_steps 的 subprocess 调用
打桩(避免真跑 pytest),专注验证搬运 / scaffold / 防漂移 / 退出码映射。
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "promote_acceptance.py"


def _load():
    spec = importlib.util.spec_from_file_location("promote_acceptance", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def pa(tmp_path, monkeypatch):
    """加载 promote 模块,把所有目录常量指向 tmp_path,checker subprocess 打桩为成功。"""
    mod = _load()
    specs = tmp_path / ".specs"
    features = tmp_path / "tests" / "acceptance" / "features"
    tests = tmp_path / "tests" / "acceptance"
    steps = tmp_path / "tests" / "acceptance" / "steps"
    for d in (specs, features, tests, steps):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "SPECS_DIR", specs)
    monkeypatch.setattr(mod, "FEATURES_DIR", features)
    monkeypatch.setattr(mod, "TESTS_DIR", tests)
    monkeypatch.setattr(mod, "STEPS_DIR", steps)
    monkeypatch.setattr(mod, "CHECKER", tmp_path / "scripts" / "check_acceptance_steps.py")

    # 默认 checker 返回 0(0 undefined);单个用例可覆盖 _rc。
    mod._rc = 0

    def fake_run(cmd, cwd=None, **kw):
        return subprocess.CompletedProcess(cmd, mod._rc)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    return mod


def _make_spec_feature(pa, feature: str, body: str = "Feature: x\n  Scenario: s\n    Given a\n"):
    d = pa.SPECS_DIR / feature
    d.mkdir(parents=True, exist_ok=True)
    (d / "acceptance.feature").write_text(body, encoding="utf-8")
    return body


# --- 名称转换 ---------------------------------------------------------------
@pytest.mark.parametrize(
    "feature,expected",
    [("my-feature", "my_feature"), ("recall_eval", "recall_eval"), ("a-b-c", "a_b_c")],
)
def test_to_snake(pa, feature, expected):
    assert pa.to_snake(feature) == expected


@pytest.mark.parametrize("bad", ["../etc", "a/b", "", "a b"])
def test_validate_feature_name_rejects(pa, bad):
    with pytest.raises(SystemExit) as exc:
        pa.validate_feature_name(bad)
    assert exc.value.code == 2


# --- 搬运 + scaffold --------------------------------------------------------
def test_promote_copies_and_scaffolds(pa):
    body = _make_spec_feature(pa, "my-feature")
    rc = pa.promote("my-feature", None)
    assert rc == 0  # checker 桩返回 0
    feat = pa.FEATURES_DIR / "my_feature.feature"
    test = pa.TESTS_DIR / "test_my_feature.py"
    steps = pa.STEPS_DIR / "my_feature_steps.py"
    assert feat.read_text(encoding="utf-8") == body  # 逐字一致(防漂移口径)
    assert test.is_file() and "scenarios(" in test.read_text(encoding="utf-8")
    assert steps.is_file()


def test_promote_missing_source_returns_2(pa):
    assert pa.promote("nope", None) == 2


def test_promote_maps_checker_rc_to_incomplete(pa):
    _make_spec_feature(pa, "feat-x")
    pa._rc = 1  # checker 报有 undefined step
    assert pa.promote("feat-x", None) == 1


def test_promote_does_not_overwrite_existing_steps(pa):
    _make_spec_feature(pa, "feat-y")
    steps = pa.STEPS_DIR / "feat_y_steps.py"
    steps.write_text("# 已有实现，勿覆盖\n", encoding="utf-8")
    pa.promote("feat-y", None)
    assert steps.read_text(encoding="utf-8") == "# 已有实现，勿覆盖\n"


# --- 防漂移 -----------------------------------------------------------------
def test_promote_overwrites_drifted_target_with_warning(pa, capsys):
    body = _make_spec_feature(pa, "feat-z", body="Feature: new\n  Scenario: s\n    Given a\n")
    drifted = pa.FEATURES_DIR / "feat_z.feature"
    drifted.write_text("Feature: OLD STALE\n", encoding="utf-8")
    pa.promote("feat-z", None)
    assert drifted.read_text(encoding="utf-8") == body  # 覆盖为 .specs 版
    assert "WARN" in capsys.readouterr().err  # 告警 durable 文件被改动


def test_promote_custom_name(pa):
    _make_spec_feature(pa, "kebab-name")
    pa.promote("kebab-name", "custom_target")
    assert (pa.FEATURES_DIR / "custom_target.feature").is_file()
    assert (pa.TESTS_DIR / "test_custom_target.py").is_file()
