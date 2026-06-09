#!/usr/bin/env python3
"""文档"内容级"事实校验：对账文档与真实代码，捕获 check_docs_sync 抓不到的失真。

check_docs_sync.py 只校验"改代码时有没有同时改文档"（文件级耦合）；本脚本补足
"文档内容对不对"（内容级对账），覆盖历史上真实发生过的三类失真：

  A. 死路径引用   —— 文档里引用的 src/ migrations/ scripts/ 路径必须真实存在
                      （如 routes/recall.py 删除后文档仍引用）
  B. MQ topic 对账 —— MQ 文档里出现的 tolink.* topic 必须是代码里真实的 MQ_NAME
                      （如散落 5 个文件的 tolink-document-pares 根本不存在）
  C. 文档内锚点   —— 仓库内 .md#anchor 链接的目标文件与锚点必须存在
                      （如召回错误码引用 §6 实为 §5 的失效锚点）

用法：
    python scripts/check_docs_facts.py            # 全量校验 docs/
    python scripts/check_docs_facts.py --quiet    # 只打印问题行
退出码：0 通过 / 1 发现问题 / 2 运行错误。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
MQ_MESSAGES_DIR = REPO_ROOT / "src" / "core" / "mq" / "messages"

# A. 死路径引用：仅校验这些"权威源码目录"开头的路径（最不可能是示意性文字，最该真实存在）
PATH_ROOTS = ("src/", "migrations/", "scripts/")
# 行内 code 或链接里、形如 src/a/b.py 的路径片段
_PATH_TOKEN = re.compile(r"(?:src|migrations|scripts)/[\w./-]+")
# B. MQ topic：真实 topic 命名空间是点状 `tolink.<...>`（如 tolink.rag.parse_task）。
#    只校验点状 token —— 连字符的 tolink-* 多为主机名/JWT iss-aud/消费组/bucket，非 topic，
#    纳入会误报。点状命名空间专属于 MQ topic，校验它即可零误报地抓住 topic 串写错。
_TOPIC_TOKEN = re.compile(r"tolink\.[\w.]+")
# 历史退役 topic 串（曾散落多个文档的失真，见 PR #169）。任何文档再次出现即视为回归。
RETIRED_TOPICS = ("tolink-document-pares",)
MQ_DOCS = (
    "api/mq_contracts.md",
    "internals/mq.md",
    "api/http_contracts.md",
    "ops/configure.md",
    "ops/deploy.md",
)
# C. markdown 链接 [text](target)
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


@dataclass
class Issue:
    check: str  # "path" / "topic" / "anchor"
    doc: str  # 相对 REPO_ROOT 的文档路径
    detail: str


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------

def _iter_doc_files() -> list[Path]:
    return sorted(DOCS_DIR.rglob("*.md"))


def _strip_inline_code_fences(text: str) -> str:
    """移除 ``` 围栏代码块，避免把示例代码里的路径/标识符当真值引用。"""
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


# ---------------------------------------------------------------------------
# A. 死路径引用
# ---------------------------------------------------------------------------

def _clean_path(token: str) -> str:
    # 去掉锚点、查询、尾随中英文标点
    token = token.split("#", 1)[0].split("?", 1)[0]
    return token.rstrip(".,;:)）、，。」』】")


def check_paths(doc: Path, body: str) -> list[Issue]:
    issues: list[Issue] = []
    seen: set[str] = set()
    for raw in _PATH_TOKEN.findall(body):
        token = _clean_path(raw)
        if not token or token in seen:
            continue
        seen.add(token)
        # 跳过 glob / 占位（versions/*.py、**、<...>）
        if any(ch in token for ch in "*<>"):
            continue
        # 跳过明显的句中无扩展名又非已知目录的噪声：只校验"看起来是文件或目录"的
        target = REPO_ROOT / token
        if target.exists():
            continue
        # 目录路径有时带尾斜杠已被 rstrip 去掉，补一次判断
        if (REPO_ROOT / token.rstrip("/")).exists():
            continue
        issues.append(
            Issue("path", _rel(doc), f"引用了不存在的路径: {token}")
        )
    return issues


# ---------------------------------------------------------------------------
# B. MQ topic 对账
# ---------------------------------------------------------------------------

def _real_mq_names() -> set[str]:
    names: set[str] = set()
    pat = re.compile(r"""MQ_NAME\s*=\s*["']([^"']+)["']""")
    for f in MQ_MESSAGES_DIR.glob("*.py"):
        for m in pat.finditer(f.read_text(encoding="utf-8")):
            names.add(m.group(1))
    return names


def check_topics(doc: Path, body: str, real_names: set[str], dlq_suffix: str) -> list[Issue]:
    issues: list[Issue] = []
    seen: set[str] = set()
    for raw in _TOPIC_TOKEN.findall(body):
        token = raw.rstrip(".,;:)）、，。")
        if token in seen:
            continue
        seen.add(token)
        base = token[: -len(dlq_suffix)] if dlq_suffix and token.endswith(dlq_suffix) else token
        if base in real_names:
            continue
        issues.append(
            Issue(
                "topic",
                _rel(doc),
                f"topic 串 `{token}` 不是代码里真实的 MQ_NAME（真实集合: {sorted(real_names)}）",
            )
        )
    return issues


def check_retired_topics(doc: Path, body: str) -> list[Issue]:
    """退役 topic 串：在任意文档（不限 MQ 文档）出现即视为回归。"""
    return [
        Issue("topic", _rel(doc), f"出现已退役的 topic 串 `{retired}`（应使用真实 MQ_NAME）")
        for retired in RETIRED_TOPICS
        if retired in body
    ]


# ---------------------------------------------------------------------------
# C. 文档内锚点链接
# ---------------------------------------------------------------------------

def _slugify(heading: str) -> str:
    """GitHub 风格锚点：小写 → 去 markdown 强调/反引号 → 删标点（保留字母/数字/CJK/连字符）→ 空格转连字符。"""
    s = heading.strip().lower()
    s = s.replace("`", "").replace("*", "")
    # 删除除"单词字符(含 CJK)、空白、连字符"以外的字符
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = s.strip().replace(" ", "-")
    return s


def _heading_slugs(path: Path) -> set[str]:
    if not path.exists():
        return set()
    slugs: set[str] = set()
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^#{1,6}\s+(.*)$", line)
        if m:
            slugs.add(_slugify(m.group(1)))
    return slugs


def check_anchors(doc: Path, body: str) -> list[Issue]:
    issues: list[Issue] = []
    for target in _MD_LINK.findall(body):
        target = target.strip()
        if "#" not in target:
            continue
        # 跳过外链
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path_part, anchor = target.split("#", 1)
        anchor = anchor.strip()
        if not anchor:
            continue
        if path_part == "":
            target_file = doc  # 同文件锚点
        else:
            target_file = (doc.parent / path_part).resolve()
        if not str(target_file).endswith(".md"):
            continue
        if not target_file.exists():
            issues.append(Issue("anchor", _rel(doc), f"链接目标文件不存在: {path_part} (锚点 #{anchor})"))
            continue
        slugs = _heading_slugs(target_file)
        if anchor not in slugs:
            issues.append(
                Issue(
                    "anchor",
                    _rel(doc),
                    f"锚点不存在: {target}（目标文件无标题匹配 #{anchor}）",
                )
            )
    return issues


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run() -> list[Issue]:
    real_names = _real_mq_names()
    # MQ_DLQ_SUFFIX 默认 .DLT（与 src/config.py 一致）；读取失败回落默认
    dlq_suffix = ".DLT"
    issues: list[Issue] = []
    mq_doc_set = {str((DOCS_DIR / rel)) for rel in MQ_DOCS}
    for doc in _iter_doc_files():
        raw = doc.read_text(encoding="utf-8")
        body = _strip_inline_code_fences(raw)
        issues += check_paths(doc, body)
        issues += check_anchors(doc, body)
        issues += check_retired_topics(doc, body)
        if str(doc) in mq_doc_set and real_names:
            issues += check_topics(doc, body, real_names, dlq_suffix)
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="文档与代码的内容级事实对账。")
    parser.add_argument("--quiet", action="store_true", help="只打印问题，不打印通过提示。")
    args = parser.parse_args(argv)

    if not DOCS_DIR.exists():
        print(f"ERROR: docs 目录不存在: {DOCS_DIR}", file=sys.stderr)
        return 2

    issues = run()
    if not issues:
        if not args.quiet:
            print("OK: 文档事实对账通过（路径 / MQ topic / 锚点）")
        return 0

    by_check: dict[str, list[Issue]] = {}
    for it in issues:
        by_check.setdefault(it.check, []).append(it)

    labels = {"path": "死路径引用", "topic": "MQ topic 对账", "anchor": "文档内锚点"}
    for check, items in by_check.items():
        print(f"\n[{labels.get(check, check)}] {len(items)} 处问题：")
        for it in items:
            print(f"  - {it.doc}: {it.detail}")
    print(f"\n共 {len(issues)} 处文档失真。修正后重试，或参见 docs/contributing.md。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
