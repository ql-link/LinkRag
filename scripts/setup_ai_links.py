#!/usr/bin/env python3
"""建立 AI 资产软链接。

.ai/ 是 skills / agents / prompts 的唯一物理来源。各 AI 工具按自己的固定
路径加载（.claude/、.agent/、CLAUDE.md、AGENTS.md），本脚本把这些路径建
为指向 .ai/ 的符号链接，从而保证多工具共享同一份内容。

新人入职、worktree 初始化、链接被误删时运行一次即可：

    python scripts/setup_ai_links.py
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# link_path -> target_path（都相对仓库根）
LINKS: dict[str, str] = {
    ".claude/skills": ".ai/skills",
    ".agent/skills":  ".ai/skills",
    "CLAUDE.md":      ".ai/prompts/project.md",
    "AGENTS.md":      ".ai/prompts/project.md",
}


def _supports_symlink() -> bool:
    probe = REPO_ROOT / ".__symlink_probe"
    try:
        probe.symlink_to(".ai")
        probe.unlink()
        return True
    except (OSError, NotImplementedError):
        if probe.exists() or probe.is_symlink():
            probe.unlink()
        return False


def _materialize(link_rel: str, target_rel: str, mode: str) -> None:
    link = REPO_ROOT / link_rel
    target = REPO_ROOT / target_rel

    if not target.exists():
        raise FileNotFoundError(f"target missing: {target_rel}")

    link.parent.mkdir(parents=True, exist_ok=True)

    if link.is_symlink() or link.exists():
        if link.is_dir() and not link.is_symlink():
            shutil.rmtree(link)
        else:
            link.unlink()

    if mode == "symlink":
        rel_target = os.path.relpath(target, link.parent)
        os.symlink(rel_target, link)
    else:
        if target.is_dir():
            shutil.copytree(target, link)
        else:
            shutil.copy(target, link)


def main() -> int:
    mode = "symlink" if _supports_symlink() else "copy"
    if mode == "copy":
        print("⚠️  当前环境不支持 symlink，降级为复制模式（Windows 请启用开发者模式）")

    for link_rel, target_rel in LINKS.items():
        _materialize(link_rel, target_rel, mode)
        print(f"  {link_rel} -> {target_rel}")

    print(f"✅ AI assets setup complete (mode={mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
