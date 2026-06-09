"""flow-guard.py 单元测试。

覆盖 LINK-108 的两条验收方向:
- 未冻结 brief 时进入 acceptance 链路被 guard 拦截
- state.yaml 通过 / 不通过 schema 校验

脚本名含连字符,无法直接 import,用 importlib 从文件路径加载。
所有用例把模块的 SPECS_DIR / _state_path 指向临时目录,互不污染。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "flow-guard.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("flow_guard", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def fg(tmp_path, monkeypatch):
    """加载 flow-guard 模块并把 .specs 根重定向到 tmp_path。"""
    mod = _load_module()
    specs = tmp_path / ".specs"
    specs.mkdir()
    monkeypatch.setattr(mod, "SPECS_DIR", specs)
    return mod


def _write_state(fg, feature: str, **overrides) -> Path:
    """生成一份合法 state.yaml,overrides 用点路径覆盖字段。"""
    data = {
        "feature": feature,
        "lane": "L3",
        "phase": "brief",
        "artifacts": {
            "brief": {"frozen": False},
            "acceptance": {"frozen": False, "promoted": False},
            "technical_design": {"frozen": False},
            "implementation": {"report_written": False},
        },
        "verified": False,
    }
    for dotted, value in overrides.items():
        node = data
        parts = dotted.split(".")
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = value
    path = fg.SPECS_DIR / feature / "state.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


# --- init -------------------------------------------------------------------
def test_init_creates_valid_state(fg):
    assert fg.cmd_init("feat-a", "L3") == 0
    assert (fg.SPECS_DIR / "feat-a" / "state.yaml").is_file()
    # init 产物本身必须过 schema
    data, issues = fg.load_state("feat-a")
    assert [i for i in issues if i.level == "error"] == []
    assert data["lane"] == "L3"


def test_init_refuses_overwrite(fg):
    assert fg.cmd_init("feat-a", "L2") == 0
    assert fg.cmd_init("feat-a", "L2") == 2  # 已存在,拒绝覆盖


def test_init_rejects_bad_lane(fg):
    assert fg.cmd_init("feat-a", "L9") == 2


# --- schema 校验 ------------------------------------------------------------
def test_validate_passes_on_good_state(fg):
    _write_state(fg, "feat-ok")
    assert fg.cmd_validate("feat-ok") == 0


def test_validate_flags_missing_fields(fg):
    issues = fg.validate_state({"feature": "x"})
    errs = {i.msg for i in issues if i.level == "error"}
    assert any("lane" in m for m in errs)
    assert any("phase" in m for m in errs)
    assert any("artifacts" in m for m in errs)


def test_validate_flags_bad_enums_and_types(fg):
    issues = fg.validate_state(
        {
            "feature": "x",
            "lane": "L9",
            "phase": "nope",
            "verified": "maybe",
            "artifacts": {"brief": {"frozen": "yes"}},
        }
    )
    errs = [i.msg for i in issues if i.level == "error"]
    assert any("lane" in m for m in errs)
    assert any("phase" in m for m in errs)
    assert any("verified" in m for m in errs)
    assert any("brief.frozen" in m for m in errs)


# --- 前置条件门禁(核心验收) ------------------------------------------------
def test_unfrozen_brief_blocks_acceptance(fg):
    """LINK-108 核心:brief 未冻结 → 进入 acceptance 被拦。"""
    _write_state(fg, "feat-b")  # brief.frozen 默认 False
    assert fg.cmd_check("feat-b", "acceptance") == 1


def test_frozen_brief_allows_acceptance(fg):
    _write_state(fg, "feat-b", **{"artifacts.brief.frozen": True})
    assert fg.cmd_check("feat-b", "acceptance") == 0


def test_l3_implementation_requires_frozen_td(fg):
    _write_state(
        fg,
        "feat-c",
        **{"artifacts.brief.frozen": True, "artifacts.acceptance.frozen": True},
    )
    # L3 缺冻结 TD → 拦截
    assert fg.cmd_check("feat-c", "implementation") == 1


def test_l2_implementation_skips_td(fg):
    _write_state(
        fg,
        "feat-d",
        lane="L2",
        **{"artifacts.brief.frozen": True, "artifacts.acceptance.frozen": True},
    )
    # L2 跳过 TD,brief+acceptance 冻结即可进实现
    assert fg.cmd_check("feat-d", "implementation") == 0


def test_done_requires_verified(fg):
    _write_state(
        fg,
        "feat-e",
        **{
            "artifacts.brief.frozen": True,
            "artifacts.acceptance.frozen": True,
            "artifacts.acceptance.promoted": True,
            "artifacts.technical_design.frozen": True,
        },
    )
    assert fg.cmd_check("feat-e", "done") == 1  # verified=False 拦截
    _write_state(
        fg,
        "feat-e",
        verified=True,
        **{
            "artifacts.brief.frozen": True,
            "artifacts.acceptance.frozen": True,
            "artifacts.acceptance.promoted": True,
            "artifacts.technical_design.frozen": True,
        },
    )
    assert fg.cmd_check("feat-e", "done") == 0


def test_brief_phase_has_no_precondition(fg):
    _write_state(fg, "feat-f")
    assert fg.cmd_check("feat-f", "brief") == 0


# --- status(LINK-109) ------------------------------------------------------
def test_status_empty_specs(fg, capsys):
    assert fg.cmd_status() == 0
    assert "无 feature" in capsys.readouterr().err


def test_status_single_active_reports_phase_and_next(fg, capsys):
    _write_state(fg, "alpha", phase="acceptance", **{"artifacts.brief.frozen": True})
    assert fg.cmd_status() == 0
    err = capsys.readouterr().err
    assert "active feature" in err
    assert "alpha" in err
    assert "acceptance" in err
    assert "acceptance-generator" in err  # 唯一下一站
    assert ".specs/alpha/brief.md" in err  # 指向该读的单文件


def test_status_multiple_inprogress_lists_all(fg, capsys):
    _write_state(fg, "alpha", phase="acceptance", **{"artifacts.brief.frozen": True})
    _write_state(fg, "beta", phase="brief")
    assert fg.cmd_status() == 0
    err = capsys.readouterr().err
    assert "2 个在途" in err
    assert "alpha" in err and "beta" in err


def test_status_all_done(fg, capsys):
    _write_state(fg, "alpha", phase="done")
    assert fg.cmd_status() == 0
    assert "无在途" in capsys.readouterr().err


def test_status_tolerates_invalid_state(fg, capsys):
    _write_state(fg, "good", phase="brief")
    bad = fg.SPECS_DIR / "bad" / "state.yaml"
    bad.parent.mkdir(parents=True)
    bad.write_text("phase: nope\n", encoding="utf-8")  # schema 不过
    assert fg.cmd_status() == 0  # 不因单个坏文件中断
    err = capsys.readouterr().err
    assert "bad" in err  # 坏文件被告警列出
    assert "good" in err  # 好文件仍被报告


# --- 输入安全 ---------------------------------------------------------------
@pytest.mark.parametrize("bad", ["../etc", "a/b", "a\\b", "", ".."])
def test_feature_name_rejects_traversal(fg, bad):
    with pytest.raises(SystemExit) as exc:
        fg.validate_feature_name(bad)
    assert exc.value.code == 2
