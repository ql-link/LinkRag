#!/usr/bin/env python3
"""Check that documentation is updated alongside code changes.

Usage:
    python scripts/check_docs_sync.py --staged              # pre-commit usage
    python scripts/check_docs_sync.py --base origin/dev     # CI usage
    python scripts/check_docs_sync.py --working             # check working tree
    python scripts/check_docs_sync.py --self-check          # validate rules file only

Exit codes:
    0  - No error-level violations (warnings may still print)
    1  - One or more error-level violations
    2  - Configuration or runtime failure (bad yaml, git unavailable, etc.)

The rules live in .claude/doc-sync-rules.yaml. See docs/development/doc_sync.md.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "ERROR: PyYAML is required. Install it with: pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULES_PATH = REPO_ROOT / ".claude" / "doc-sync-rules.yaml"


# ---------------------------------------------------------------------------
# Glob matching with ** support
# ---------------------------------------------------------------------------

def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a glob pattern (with `**` support) to a compiled regex.

    Rules:
      `**/`   -> matches any number of path components, including zero
      `**`    -> matches anything (including `/`)
      `*`     -> matches anything except `/`
      `?`     -> matches a single non-`/` char
      others  -> matched literally (regex metacharacters escaped)
    """
    parts: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            # `**` (possibly followed by /)
            if i + 1 < n and pattern[i + 1] == "*":
                if i + 2 < n and pattern[i + 2] == "/":
                    parts.append("(?:.*/)?")
                    i += 3
                else:
                    parts.append(".*")
                    i += 2
            else:
                parts.append("[^/]*")
                i += 1
        elif c == "?":
            parts.append("[^/]")
            i += 1
        elif c in r".+()[]{}^$|\\":
            parts.append("\\" + c)
            i += 1
        else:
            parts.append(c)
            i += 1
    return re.compile("^" + "".join(parts) + "$")


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(_glob_to_regex(p).match(path) for p in patterns)


# ---------------------------------------------------------------------------
# Rule loading
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    when_changed: tuple[str, ...]
    must_update: tuple[str, ...]
    severity: str
    rationale: str
    forbid_change: bool = False


def load_rules(path: Path) -> list[Rule]:
    if not path.exists():
        raise FileNotFoundError(f"Rules file not found: {path}")
    with path.open("r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}

    if data.get("version") != 1:
        raise ValueError(f"Unsupported rules version: {data.get('version')}")

    defaults = data.get("defaults", {})
    default_severity = defaults.get("severity", "warning")

    rules: list[Rule] = []
    seen_ids: set[str] = set()
    for raw in data.get("rules", []):
        rule_id = raw.get("id")
        if not rule_id:
            raise ValueError(f"Rule missing 'id': {raw}")
        if rule_id in seen_ids:
            raise ValueError(f"Duplicate rule id: {rule_id}")
        seen_ids.add(rule_id)

        when_changed = raw.get("when_changed") or []
        must_update = raw.get("must_update") or []
        forbid_change = bool(raw.get("forbid_change", False))
        if not when_changed:
            raise ValueError(f"Rule '{rule_id}' must have when_changed")
        if not forbid_change and not must_update:
            raise ValueError(
                f"Rule '{rule_id}' must have must_update (or set forbid_change: true)"
            )
        if forbid_change and must_update:
            raise ValueError(
                f"Rule '{rule_id}' cannot combine forbid_change with must_update"
            )

        severity = raw.get("severity", default_severity)
        if severity not in ("error", "warning"):
            raise ValueError(
                f"Rule '{rule_id}' has invalid severity: {severity!r}"
            )

        rules.append(
            Rule(
                id=rule_id,
                description=raw.get("description", ""),
                when_changed=tuple(when_changed),
                must_update=tuple(must_update),
                severity=severity,
                rationale=raw.get("rationale", ""),
                forbid_change=forbid_change,
            )
        )
    return rules


# ---------------------------------------------------------------------------
# Git diff helpers
# ---------------------------------------------------------------------------

def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git is not installed or not on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"git command failed: git {' '.join(args)}\n{exc.stderr}"
        ) from exc
    return out.stdout


def get_changed_files(mode: str, base: str | None) -> set[str]:
    """Return the set of changed file paths relative to repo root.

    Modes:
        staged   - files in git index (pre-commit usage)
        base     - files differing from `base` ref (CI usage)
        working  - all uncommitted changes (working tree + index)
    """
    if mode == "staged":
        raw = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    elif mode == "base":
        if not base:
            raise ValueError("--base requires a ref")
        # `A...B` shows files changed on the branch since the merge base
        raw = _git("diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD")
    elif mode == "working":
        raw = _git("diff", "--name-only", "--diff-filter=ACMR", "HEAD")
    else:
        raise ValueError(f"Unknown mode: {mode}")

    return {line.strip() for line in raw.splitlines() if line.strip()}


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

@dataclass
class Violation:
    rule: Rule
    triggers: list[str]
    missing: list[str]


def find_violations(rules: list[Rule], changed: set[str]) -> list[Violation]:
    violations: list[Violation] = []
    for rule in rules:
        triggers = sorted(p for p in changed if _matches_any(p, list(rule.when_changed)))
        if not triggers:
            continue
        if rule.forbid_change:
            # The mere act of changing a forbidden file is the violation;
            # there is no companion file to satisfy.
            violations.append(Violation(rule=rule, triggers=triggers, missing=[]))
            continue
        # Each entry in must_update is treated as a glob pattern. The rule
        # is satisfied if at least one changed file matches the pattern; the
        # entry is reported as "missing" otherwise. Plain paths (no wildcard)
        # degrade to exact-match, preserving prior behavior.
        missing = sorted(
            pattern
            for pattern in rule.must_update
            if not any(_glob_to_regex(pattern).match(p) for p in changed)
        )
        if missing:
            violations.append(Violation(rule=rule, triggers=triggers, missing=missing))
    return violations


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_USE_COLOR = sys.stdout.isatty()


def _color(text: str, code: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def _red(text: str) -> str:
    return _color(text, "31;1")


def _yellow(text: str) -> str:
    return _color(text, "33;1")


def _green(text: str) -> str:
    return _color(text, "32;1")


def _dim(text: str) -> str:
    return _color(text, "2")


def print_violations(violations: list[Violation], quiet: bool) -> None:
    for v in violations:
        tag = _red("[ERROR]") if v.rule.severity == "error" else _yellow("[WARN ]")
        print(f"{tag} {v.rule.id}: {v.rule.description}")
        if not quiet:
            for trigger in v.triggers:
                if v.rule.forbid_change:
                    print(f"  ✗ forbidden change: {trigger}")
                else:
                    print(f"  ↳ changed: {trigger}")
        for doc in v.missing:
            print(f"  ✗ missing update: {doc}")
        if v.rule.rationale and not quiet:
            print(f"  {_dim('why: ' + v.rule.rationale)}")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check that documentation is updated alongside code changes.",
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--staged",
        action="store_true",
        help="Check staged files (pre-commit mode).",
    )
    target.add_argument(
        "--base",
        metavar="REF",
        help="Check files changed relative to REF (e.g. origin/dev) for CI.",
    )
    target.add_argument(
        "--working",
        action="store_true",
        help="Check all uncommitted changes including unstaged.",
    )
    target.add_argument(
        "--self-check",
        action="store_true",
        help="Only validate the rules file is well-formed; do no git checks.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_RULES_PATH,
        help=f"Rules file path (default: {DEFAULT_RULES_PATH.relative_to(REPO_ROOT)}).",
    )
    parser.add_argument(
        "--warning-as-error",
        action="store_true",
        help="Treat warning-level violations as errors (also affects exit code).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Print only the violation header lines; omit rationale and triggers.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        rules = load_rules(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"{_red('ERROR')}: {exc}", file=sys.stderr)
        return 2

    if args.self_check:
        print(_green(f"OK: loaded {len(rules)} rule(s) from {args.config}"))
        return 0

    # Pick mode
    if args.staged:
        mode, base = "staged", None
    elif args.base:
        mode, base = "base", args.base
    elif args.working:
        mode, base = "working", None
    else:
        # Default to staged (matches pre-commit hook common case)
        mode, base = "staged", None

    try:
        changed = get_changed_files(mode, base)
    except (RuntimeError, ValueError) as exc:
        print(f"{_red('ERROR')}: {exc}", file=sys.stderr)
        return 2

    if not changed:
        if not args.quiet:
            print(_green("No changed files — nothing to check."))
        return 0

    violations = find_violations(rules, changed)
    print_violations(violations, args.quiet)

    error_count = sum(1 for v in violations if v.rule.severity == "error")
    warning_count = sum(1 for v in violations if v.rule.severity == "warning")
    total_changed = len(changed)

    if violations:
        summary = (
            f"Checked {total_changed} changed file(s) | "
            f"{_red(str(error_count) + ' error')}, "
            f"{_yellow(str(warning_count) + ' warning')}"
        )
        print(summary)
    else:
        print(_green(f"OK: {total_changed} changed file(s), no doc-sync issues"))

    blocking = error_count + (warning_count if args.warning_as_error else 0)
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
