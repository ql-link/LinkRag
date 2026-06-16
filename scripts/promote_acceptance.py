#!/usr/bin/env python3
"""把 acceptance.feature 从 .specs 提升到 tests/——搬运 + 校验,取代手工 copy(LINK-110)。

合并前需把 ``.specs/<feature>/acceptance.feature`` 提升到 ``tests/acceptance/features/``
才能进 git、被 pytest-bdd 长期运行。过去这步是手工 copy(脚本里写在 skill 文本里),
两份会漂、且没人校验提升后每条 Scenario 的 step 都绑定了。本脚本把它变成可验证操作:

1. 搬运:``.specs/<feature>/acceptance.feature`` → ``tests/acceptance/features/<name>.feature``
   (feature 目录名是 kebab-case,目标按现有约定转 snake_case)
2. scaffold:若缺,生成配套 ``test_<name>.py``(scenarios 绑定 + star-import steps 模块)
   和空的 ``steps/<name>_steps.py``(让 pytest 能收集;未实现的 step 由下一步暴露)
3. 防漂移:提升后令 tests/ 版与 .specs 版逐字一致(目标已存在且不同则覆盖并告警)
4. 校验:调 ``check_acceptance_steps.py`` 断言 0 个 undefined step

Usage:
    python scripts/promote_acceptance.py <feature> [--name <snake_name>]

Exit codes:
    0  - 提升完成且 0 undefined step
    1  - 提升完成但仍有 undefined step(需实现 step 后重跑)
    2  - 运行期失败(源缺失、名字非法等)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = REPO_ROOT / ".specs"
FEATURES_DIR = REPO_ROOT / "tests" / "acceptance" / "features"
TESTS_DIR = REPO_ROOT / "tests" / "acceptance"
STEPS_DIR = REPO_ROOT / "tests" / "acceptance" / "steps"
CHECKER = REPO_ROOT / "scripts" / "check_acceptance_steps.py"


def _err(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def validate_feature_name(name: str) -> None:
    """拒绝空名、路径穿越与非法字符(同 flow-guard 口径)。"""
    if not name or ".." in name or "/" in name or "\\" in name:
        _err(f"非法 feature 名: '{name}'")
        sys.exit(2)
    if not all(c.isalnum() or c in "-_" for c in name):
        _err(f"非法 feature 名: '{name}'(仅允许 a-z A-Z 0-9 - _)")
        sys.exit(2)


def to_snake(feature: str) -> str:
    """kebab-case feature 目录名 → snake_case 测试名(现有 tests/acceptance 约定)。"""
    name = feature.replace("-", "_")
    if not name[0].isalpha() and name[0] != "_":
        # 目标会变成 test_<name>.py / <name>_steps.py 的标识符片段,首字符须合法
        name = f"f_{name}"
    return name


TEST_TEMPLATE = '''\
"""pytest-bdd 入口:加载 {name} acceptance.feature(由 promote_acceptance.py 生成)。

step 实现见 ``tests/acceptance/steps/{name}_steps.py``。pytest-bdd 通过 star-import
在本测试模块命名空间发现 step 函数;若某 Scenario 缺少 step 绑定,运行时抛
StepDefinitionNotFoundError——覆盖完整性由 check_acceptance_steps.py 守。
"""

from pathlib import Path

from pytest_bdd import scenarios

from tests.acceptance.steps.{name}_steps import *  # noqa: F401,F403

_FEATURE = Path(__file__).resolve().parent / "features" / "{name}.feature"

scenarios(str(_FEATURE))
'''

STEPS_TEMPLATE = '''\
"""{name} 的 pytest-bdd step 实现。

由 promote_acceptance.py 生成的空骨架——在此补 @given/@when/@then,直到
``python scripts/check_acceptance_steps.py`` 报 0 undefined step。
"""

from __future__ import annotations
'''


def promote(feature: str, name: str | None) -> int:
    src = SPECS_DIR / feature / "acceptance.feature"
    if not src.is_file():
        _err(f"源文件不存在: {src}")
        print("  Next: 先在 .specs 下生成并冻结 acceptance.feature", file=sys.stderr)
        return 2

    target_name = name or to_snake(feature)
    feature_dst = FEATURES_DIR / f"{target_name}.feature"
    test_dst = TESTS_DIR / f"test_{target_name}.py"
    steps_dst = STEPS_DIR / f"{target_name}_steps.py"

    FEATURES_DIR.mkdir(parents=True, exist_ok=True)
    STEPS_DIR.mkdir(parents=True, exist_ok=True)

    src_text = src.read_text(encoding="utf-8")

    # 1+3. 搬运 + 防漂移:目标已存在且内容不同 → 覆盖使其一致,并告警(durable 文件被改动)。
    if feature_dst.exists():
        old = feature_dst.read_text(encoding="utf-8")
        if old != src_text:
            print(
                f"[WARN] {feature_dst.relative_to(REPO_ROOT)} 已存在且与 .specs 版不同,"
                f"覆盖为 .specs 版(消除漂移)",
                file=sys.stderr,
            )
    feature_dst.write_text(src_text, encoding="utf-8")
    print(f"[PROMOTE] {src.relative_to(REPO_ROOT)} → {feature_dst.relative_to(REPO_ROOT)}", file=sys.stderr)

    # 一致性自检:写入后两版必须逐字相等(锁定口径:promote 时令两者一致即可)。
    assert feature_dst.read_text(encoding="utf-8") == src_text

    # 2. scaffold 配套 test_ 与 steps_(仅在缺失时,不覆盖已有实现)。
    if not test_dst.exists():
        test_dst.write_text(TEST_TEMPLATE.format(name=target_name), encoding="utf-8")
        print(f"[SCAFFOLD] {test_dst.relative_to(REPO_ROOT)}", file=sys.stderr)
    if not steps_dst.exists():
        steps_dst.write_text(STEPS_TEMPLATE.format(name=target_name), encoding="utf-8")
        print(f"[SCAFFOLD] {steps_dst.relative_to(REPO_ROOT)}(空骨架,待实现 step)", file=sys.stderr)

    # 4. 校验:提升后跑 undefined-step 门禁(只针对本 feature 的 test 文件)。
    rel_test = test_dst.relative_to(REPO_ROOT).as_posix()
    proc = subprocess.run(
        [sys.executable, str(CHECKER), rel_test],
        cwd=REPO_ROOT,
    )
    if proc.returncode == 0:
        print(f"[OK] {target_name} 已提升且 0 undefined step", file=sys.stderr)
        return 0
    if proc.returncode == 1:
        print(
            f"[INCOMPLETE] {target_name} 已搬运,但仍有未实现 step——"
            f"补全 steps/{target_name}_steps.py 后重跑本脚本",
            file=sys.stderr,
        )
        return 1
    return 2  # 校验脚本运行期失败


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="提升 acceptance.feature 到 tests/ 并校验。")
    parser.add_argument("feature", help=".specs 下的 feature 目录名(kebab-case)")
    parser.add_argument("--name", default=None, help="目标 snake_case 名(默认由 feature 自动转换)")
    args = parser.parse_args(argv)

    validate_feature_name(args.feature)
    if args.name is not None:
        validate_feature_name(args.name)
    return promote(args.feature, args.name)


if __name__ == "__main__":
    sys.exit(main())
