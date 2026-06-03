#!/usr/bin/env python3
"""校验 AI 资产软链接的完整性。

防止有人把 .claude/skills、.agent/skills 等链接误删后重建为实目录，
导致 .ai/ 失去单一事实源的地位。pre-commit 与 CI 会执行此脚本。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# link_path -> 期望的链接目标字符串（相对 link 自身所在目录）
EXPECTED: dict[str, str] = {
    ".claude/skills": "../.ai/skills",
    ".agent/skills":  "../.ai/skills",
    "CLAUDE.md":      ".ai/prompts/project.md",
    "AGENTS.md":      ".ai/prompts/project.md",
}


def main() -> int:
    failures: list[str] = []

    for link_rel, expected_target in EXPECTED.items():
        link = REPO_ROOT / link_rel
        if not link.is_symlink():
            failures.append(f"{link_rel} 不是 symlink（运行 `python scripts/setup_ai_links.py` 修复）")
            continue

        actual = os.readlink(link)
        if actual != expected_target:
            failures.append(
                f"{link_rel} 指向 `{actual}`，应为 `{expected_target}`"
            )

        if not link.resolve().exists():
            failures.append(f"{link_rel} 是死链：目标 {link.resolve()} 不存在")

    if failures:
        for msg in failures:
            print(f"❌ {msg}")
        return 1

    print("✅ AI links OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
