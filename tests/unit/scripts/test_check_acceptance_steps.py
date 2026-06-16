"""check_acceptance_steps.py 单元测试。

只测纯逻辑(scan_output 解析、main 对不存在目标的处理),不在单测里真跑 pytest
子进程——那是慢且依赖环境的集成行为,已在开发期手工验证。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "check_acceptance_steps.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_acceptance_steps", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CAS = _load()


SAMPLE_WITH_UNDEFINED = """\
tests/acceptance/test_x.py::test_s F
E   pytest_bdd.exceptions.StepDefinitionNotFoundError: Step definition is not found: Given "缺失前置 xyz". Line 3 in scenario "s" in the feature "/repo/x.feature"
tests/acceptance/test_y.py::test_t F
E   pytest_bdd.exceptions.StepDefinitionNotFoundError: Step definition is not found: When "另一个未绑定 abc". Line 5 in scenario "t" in the feature "/repo/y.feature"
"""


def test_scan_output_extracts_undefined_steps():
    found = CAS.scan_output(SAMPLE_WITH_UNDEFINED)
    assert len(found) == 2
    assert found[0].startswith('Given "缺失前置 xyz"')
    assert found[1].startswith('When "另一个未绑定 abc"')


def test_scan_output_dedupes():
    text = SAMPLE_WITH_UNDEFINED + SAMPLE_WITH_UNDEFINED  # 重复两遍
    assert len(CAS.scan_output(text)) == 2


def test_scan_output_clean_returns_empty():
    assert CAS.scan_output("34 failed, 150 passed in 15s\nE assert 1 == 2") == []


def test_scan_output_ignores_assertion_failures():
    # 普通断言失败不含 "Step definition is not found",不应被当成 undefined step
    text = "E   AssertionError: assert task.status == FAILED\nE   assert 'OK' == 'FAILED'"
    assert CAS.scan_output(text) == []


def test_main_returns_2_on_missing_target(capsys):
    assert CAS.main(["tests/acceptance/__does_not_exist__"]) == 2
    assert "不存在" in capsys.readouterr().err
