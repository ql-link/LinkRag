#!/usr/bin/env python3
"""Acceptance step-binding 门禁:确保 tests/acceptance 下每个 Scenario 的 step 都已绑定。

undefined step 是 acceptance 从 .specs 提升到 tests/(LINK-110)最脆的一环:.feature
搬过来后,若某 step 没有对应的 @given/@when/@then 实现,pytest-bdd 在运行时抛
``StepDefinitionNotFoundError``。本脚本运行 acceptance 套件,**只**捕捉这类绑定缺失,
与普通断言失败解耦——断言红(逻辑没写对)不影响本门禁,那是 run-all-tests 的职责。

为何不用 ``--generate-missing``:它对 ``Scenario Outline`` 的 parser step 会误报
"未定义"(实际运行时能匹配),不可靠;运行期的 ``StepDefinitionNotFoundError`` 只对
真正未绑定的 step 触发,是唯一可信信号。

注意:pytest-bdd 在一个 Scenario 内遇到第一个未绑定 step 即抛错,后续 step 不再检查。
因此一个 Scenario 可能要修完一个再暴露下一个;本门禁报"存在 undefined",迭代修复即可。

Usage:
    python scripts/check_acceptance_steps.py                 # 全量 tests/acceptance(CI 门禁)
    python scripts/check_acceptance_steps.py <path>          # 指定 test 文件/目录(promote 复用)

Exit codes:
    0  - 无 undefined step
    1  - 存在 undefined step(打印 HARD STOP + 清单)
    2  - 运行期失败(pytest 不可用、目标不存在等)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = "tests/acceptance"

# 运行期错误形如:
#   StepDefinitionNotFoundError: Step definition is not found: Given "xxx". Line 3 in scenario "s" ...
# pytest-bdd 内部用英文关键字 Given/When/Then(即便 step 文本是中文),据此精确截取 step。
_STEP_RE = re.compile(
    r'Step definition is not found:\s*((?:Given|When|Then|And|But)\s+"[^"]*"[^\n]*)'
)


def scan_output(text: str) -> list[str]:
    """从 pytest 输出里提取 undefined step 描述(去重保序)。"""
    found: list[str] = []
    for m in _STEP_RE.finditer(text):
        item = m.group(1).strip()
        if item not in found:
            found.append(item)
    return found


def run_pytest(target: str) -> tuple[int, str]:
    """对 target 运行 pytest(--tb=line 让 StepDefinitionNotFoundError 单行可解析)。

    返回 (pytest 退出码, 合并输出)。pytest 退出码在此**不直接决定门禁结果**——
    断言失败也会让 pytest 退出非 0,但那不是 undefined step。
    """
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        target,
        "--tb=line",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    target = argv[0] if argv else DEFAULT_TARGET

    target_path = (REPO_ROOT / target).resolve()
    if not target_path.exists():
        print(f"ERROR: 目标不存在: {target}", file=sys.stderr)
        return 2

    rc, output = run_pytest(target)

    # pytest 收集期错误(rc==2 且无任何测试)通常意味着 import 失败等环境问题,
    # 与 undefined step 不同,按运行期失败处理,避免误判为"通过"。
    if rc == 2 and "no tests ran" in output and "not found" not in output:
        print("ERROR: pytest 运行失败(收集期错误),无法判定 undefined step:", file=sys.stderr)
        print(output[-2000:], file=sys.stderr)
        return 2

    undefined = scan_output(output)
    if undefined:
        print("=== HARD STOP: 存在未绑定的 acceptance step ===", file=sys.stderr)
        for s in undefined:
            print(f"  [UNDEFINED] {s}", file=sys.stderr)
        print(
            f"  Next: 在 tests/acceptance/steps/ 下实现上述 step(@given/@when/@then),"
            f"或修正 .feature 文本使其匹配现有 step",
            file=sys.stderr,
        )
        print(f"共 {len(undefined)} 个未绑定 step(目标: {target})", file=sys.stderr)
        return 1

    print(f"[OK] 无 undefined step(目标: {target})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
