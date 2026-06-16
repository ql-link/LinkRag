#!/usr/bin/env python3
"""Flow guard — feature 交付流程的阶段门禁(机器拥有的状态 + 前置校验)。

替代手维护的 ``.specs/<feature>/feature_info.md``:阶段不变量改由 schema 化的
``.specs/<feature>/state.yaml`` 记录,进入下游 skill 前用本脚本校验前置条件,
不满足就打印 ``HARD STOP`` + 可执行的下一步。参考 rpamis/comet 的
``.comet.yaml`` + ``comet-yaml-validate`` + ``comet-guard`` 三件套思路,用
Python 重写以对齐本仓 ``scripts/`` 既有校验脚本风格(见 ``check_skills.py``)。

设计约束:``.specs/`` 整目录 git-ignored,所以本脚本**不是** git hook,而是由
各 skill 在运行时主动调用(``python scripts/flow-guard.py check <feature> <phase>``)。

子命令:
    init <feature> [--lane L2|L3]   按模板生成 state.yaml(已存在则拒绝覆盖)
    validate <feature>              仅做 schema 结构校验
    check <feature> <phase>         schema 校验 + 进入 <phase> 的前置条件校验(主入口)

phase 取值(state.yaml 的 ``phase`` 字段 / check 的目标):
    brief -> acceptance -> technical_design -> implementation -> done

Usage:
    python scripts/flow-guard.py init my-feature --lane L3
    python scripts/flow-guard.py validate my-feature
    python scripts/flow-guard.py check my-feature acceptance

Exit codes:
    0  - 通过(可能有 warning)
    1  - 被拦截(前置条件不满足)或 schema 校验失败
    2  - 运行期失败(参数非法、文件缺失、yaml 不可用等)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - 环境缺依赖时的兜底提示
    print("ERROR: PyYAML is required. Install it with: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = REPO_ROOT / ".specs"

# 终端着色:仅在 TTY 下上色,避免污染被 skill 捕获的输出。
def _color(code: str, text: str) -> str:
    if sys.stderr.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text


def red(text: str) -> str:
    return _color("31", text)


def green(text: str) -> str:
    return _color("32", text)


def yellow(text: str) -> str:
    return _color("33", text)


# --- state.yaml schema 定义 -------------------------------------------------
# 车道:L1 小改动不走 .specs 全链;进入本流程的只有 L2 / L3。
VALID_LANES = ("L2", "L3")

# 阶段线性推进。done 表示实现已通过验证、可进入收口。
PHASE_ORDER = ("brief", "acceptance", "technical_design", "implementation", "done")
VALID_PHASES = PHASE_ORDER

# phase -> 该阶段应工作的 skill(下一站) + 恢复工作所需的最小输入文件清单。
# status 用它把"我在第几站、该读哪个文件"一次性报出,避免跨会话重读全部 .specs 产物。
# 语义:phase=X 表示已放行到第 X 站(冻结上一站产物时由对应 skill 推进而来),
# 因此 phase 字段本身即"当前唯一允许的下一站"。
STATION = {
    "brief": ("brief-generator", ["(收敛需求中,暂无上游输入)"]),
    "acceptance": ("acceptance-generator", ["brief.md"]),
    "technical_design": ("technical-design", ["brief.md", "acceptance.feature"]),
    "implementation": (
        "implementation-execution",
        ["brief.md", "acceptance.feature", "technical_design.md(L3)"],
    ),
    "done": (None, []),  # 已完成:无下一站,进收口/清理
}

# artifacts 子结构:每个 artifact 的布尔不变量。
# key -> 该 artifact 下允许出现的布尔字段集合。
ARTIFACT_FIELDS = {
    "brief": ("frozen",),
    "acceptance": ("frozen", "promoted"),
    "technical_design": ("frozen",),
    "implementation": ("report_written",),
}

# 顶层必填字段。``notes`` 为人类可读摘要(取代 feature_info.md 的人读职能),
# 选填、不参与机器校验。
REQUIRED_TOP_FIELDS = ("feature", "lane", "phase", "artifacts", "verified")


class Issue:
    """单条校验问题。"""

    def __init__(self, level: str, msg: str, nxt: str | None = None) -> None:
        self.level = level  # "error" | "warning"
        self.msg = msg
        self.nxt = nxt  # 可执行的下一步(仅 error 常用)


# --- 输入安全 ---------------------------------------------------------------
def validate_feature_name(name: str) -> None:
    """拒绝空名、非法字符与路径穿越,防止 state.yaml 路径被构造到目录外。"""
    if not name:
        print(red("ERROR: feature 名不能为空"), file=sys.stderr)
        sys.exit(2)
    if ".." in name or "/" in name or "\\" in name:
        print(red(f"ERROR: 非法 feature 名(禁止路径分隔符 / 穿越): '{name}'"), file=sys.stderr)
        sys.exit(2)
    if not all(c.isalnum() or c in "-_" for c in name):
        print(red(f"ERROR: 非法 feature 名: '{name}'(仅允许 a-z A-Z 0-9 - _)"), file=sys.stderr)
        sys.exit(2)


def _state_path(feature: str) -> Path:
    return SPECS_DIR / feature / "state.yaml"


# --- schema 校验 ------------------------------------------------------------
def _is_bool(value: object) -> bool:
    return isinstance(value, bool)


def validate_state(data: object) -> list[Issue]:
    """对已加载的 state.yaml 数据做结构 + 取值校验,返回问题列表。"""
    issues: list[Issue] = []

    if not isinstance(data, dict):
        return [Issue("error", "state.yaml 顶层必须是映射(mapping)")]

    for field in REQUIRED_TOP_FIELDS:
        if field not in data:
            issues.append(Issue("error", f"缺少必填字段 '{field}'"))

    lane = data.get("lane")
    if lane is not None and lane not in VALID_LANES:
        issues.append(Issue("error", f"lane='{lane}' 非法,应为 {list(VALID_LANES)}"))

    phase = data.get("phase")
    if phase is not None and phase not in VALID_PHASES:
        issues.append(Issue("error", f"phase='{phase}' 非法,应为 {list(VALID_PHASES)}"))

    if "verified" in data and not _is_bool(data["verified"]):
        issues.append(Issue("error", "verified 必须是布尔值(true/false)"))

    artifacts = data.get("artifacts")
    if artifacts is not None:
        if not isinstance(artifacts, dict):
            issues.append(Issue("error", "artifacts 必须是映射"))
        else:
            for key in ARTIFACT_FIELDS:
                if key not in artifacts:
                    issues.append(Issue("error", f"artifacts 缺少子项 '{key}'"))
            for key, sub in artifacts.items():
                if key not in ARTIFACT_FIELDS:
                    issues.append(Issue("warning", f"artifacts 含未知子项 '{key}'"))
                    continue
                if not isinstance(sub, dict):
                    issues.append(Issue("error", f"artifacts.{key} 必须是映射"))
                    continue
                for bf in ARTIFACT_FIELDS[key]:
                    if bf in sub and not _is_bool(sub[bf]):
                        issues.append(Issue("error", f"artifacts.{key}.{bf} 必须是布尔值"))

    return issues


def load_state(feature: str) -> tuple[dict | None, list[Issue]]:
    """读取并解析 state.yaml;返回 (数据, schema 问题列表)。

    文件缺失 / yaml 语法错误以退出码 2 直接终止(运行期失败,不算"被拦截")。
    """
    path = _state_path(feature)
    if not path.is_file():
        print(red(f"ERROR: 未找到 state.yaml: {path}"), file=sys.stderr)
        print(
            yellow(f"  Next: 先运行 `python scripts/flow-guard.py init {feature}` 初始化阶段状态"),
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(red(f"ERROR: state.yaml 不是合法 YAML: {exc}"), file=sys.stderr)
        sys.exit(2)
    return (data if isinstance(data, dict) else None), validate_state(data)


# --- 阶段前置条件 -----------------------------------------------------------
def _artifact_flag(data: dict, artifact: str, flag: str) -> bool:
    arts = data.get("artifacts") or {}
    sub = arts.get(artifact) or {}
    return bool(sub.get(flag))


def check_preconditions(data: dict, target_phase: str) -> list[Issue]:
    """校验"进入 target_phase"所需的前置条件,返回未满足项(error 带 Next)。

    这是本脚本的核心:把散落在各 skill 自然语言里的"若上游未冻结→转回"沉淀为
    确定性判定。L2 车道跳过 technical_design,放行直接进 implementation。
    """
    issues: list[Issue] = []
    lane = data.get("lane")

    if target_phase == "brief":
        return issues  # brief 是链起点,无上游前置

    if target_phase == "acceptance":
        if not _artifact_flag(data, "brief", "frozen"):
            issues.append(
                Issue(
                    "error",
                    "brief 尚未冻结,不能生成 acceptance",
                    "回到 brief-generator 收敛待确认问题并冻结(artifacts.brief.frozen=true)",
                )
            )
        return issues

    if target_phase == "technical_design":
        if not _artifact_flag(data, "brief", "frozen"):
            issues.append(Issue("error", "brief 尚未冻结", "回 brief-generator 冻结 brief"))
        if not _artifact_flag(data, "acceptance", "frozen"):
            issues.append(
                Issue("error", "acceptance 尚未冻结", "回 acceptance-generator 冻结 acceptance")
            )
        return issues

    if target_phase == "implementation":
        if not _artifact_flag(data, "brief", "frozen"):
            issues.append(Issue("error", "brief 尚未冻结", "回 brief-generator 冻结 brief"))
        if not _artifact_flag(data, "acceptance", "frozen"):
            issues.append(
                Issue("error", "acceptance 尚未冻结", "回 acceptance-generator 冻结 acceptance")
            )
        # L3 必须有冻结的 TD;L2 跳过独立 technical-design(见 flow-router 车道定义)。
        if lane == "L3" and not _artifact_flag(data, "technical_design", "frozen"):
            issues.append(
                Issue(
                    "error",
                    "L3 车道要求 technical_design 冻结后才能进实现",
                    "回 technical-design 冻结技术方案(artifacts.technical_design.frozen=true)",
                )
            )
        return issues

    if target_phase == "done":
        if not data.get("verified"):
            issues.append(
                Issue(
                    "error",
                    "实现尚未通过验证,不能标记完成",
                    "跑 run-all-tests 全绿后置 verified=true",
                )
            )
        # 收口前 acceptance 应已提升到 tests/(promoted),否则追溯链断裂。
        if not _artifact_flag(data, "acceptance", "promoted"):
            issues.append(
                Issue(
                    "warning",
                    "acceptance 尚未提升到 tests/acceptance/features/(promoted=false)",
                    "在 branch-pr-workflow 收口时提升 acceptance 并置 promoted=true",
                )
            )
        return issues

    issues.append(Issue("error", f"未知目标阶段 '{target_phase}',应为 {list(VALID_PHASES)}"))
    return issues


# --- 输出 -------------------------------------------------------------------
def _print_issues(issues: list[Issue], header_ok: str) -> int:
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]

    if errors:
        print(red("=== HARD STOP ==="), file=sys.stderr)
        for i in errors:
            print(red(f"  [FAIL] {i.msg}"), file=sys.stderr)
            if i.nxt:
                print(yellow(f"    Next: {i.nxt}"), file=sys.stderr)
    for i in warnings:
        print(yellow(f"  [WARN] {i.msg}"), file=sys.stderr)
        if i.nxt:
            print(yellow(f"    Next: {i.nxt}"), file=sys.stderr)

    if not errors:
        print(green(header_ok), file=sys.stderr)
    return 1 if errors else 0


# --- 子命令实现 -------------------------------------------------------------
STATE_TEMPLATE = """\
# .specs/{feature}/state.yaml — feature 阶段状态(机器拥有,取代手维护的 feature_info.md)
#
# 由 flow-guard.py 校验,各 skill 在阶段推进时显式回写(冻结 = 把对应 frozen 置 true)。
# 机器不变量在结构化字段里;人类可读摘要放 notes(不参与校验)。

feature: {feature}
lane: {lane}                      # 车道:L2 跳过 technical_design,L3 走完整链
phase: brief                      # 当前阶段:brief|acceptance|technical_design|implementation|done

artifacts:
  brief:
    frozen: false                 # brief 是否已冻结(冻结后方可生成 acceptance)
  acceptance:
    frozen: false                 # acceptance 是否已冻结
    promoted: false               # 是否已提升到 tests/acceptance/features/
  technical_design:
    frozen: false                 # 技术方案是否已冻结(仅 L3 要求)
  implementation:
    report_written: false         # 是否已写 implementation_report.md

verified: false                   # 实现是否已通过验证(测试全绿)

# 人类可读摘要:推荐阅读顺序、产物清单、任意说明。机器不校验本字段。
notes: |
  (在此记录推荐阅读顺序与产物清单)
"""


def _scan_features() -> tuple[list[tuple[str, dict]], list[str]]:
    """扫描 .specs/ 下所有带 state.yaml 的 feature。

    返回 (valid, invalid):
    - valid: [(feature, data)],data 已过 schema 校验
    - invalid: 文件损坏 / yaml 非法 / schema 不过的 feature 名

    不调用会 sys.exit 的 load_state——status 要容忍单个坏文件,继续报其余。
    """
    valid: list[tuple[str, dict]] = []
    invalid: list[str] = []
    if not SPECS_DIR.is_dir():
        return valid, invalid
    for child in sorted(SPECS_DIR.iterdir()):
        if not child.is_dir():
            continue
        sp = child / "state.yaml"
        if not sp.is_file():
            continue
        try:
            data = yaml.safe_load(sp.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            invalid.append(child.name)
            continue
        if not isinstance(data, dict) or any(
            i.level == "error" for i in validate_state(data)
        ):
            invalid.append(child.name)
            continue
        valid.append((child.name, data))
    return valid, invalid


def _render_feature(feature: str, data: dict) -> list[str]:
    """把单个 feature 的恢复信息渲染成多行文本:feature/lane/phase/下一站/待读文件。"""
    phase = data.get("phase", "?")
    lane = data.get("lane", "?")
    skill, reads = STATION.get(phase, (None, []))
    lines = [f"feature : {feature}", f"lane    : {lane}", f"phase   : {phase}"]
    if phase == "done":
        lines.append("下一站  : (已完成)进入收口 branch-pr-workflow 或合并后 rm -rf 清理")
        return lines
    # 当前站产物若已冻结,说明状态本应推进,提示一句(正常情况下不该出现)。
    art = phase if phase in ARTIFACT_FIELDS else None
    frozen = bool((data.get("artifacts") or {}).get(art, {}).get("frozen")) if art else False
    # 真实产物名补上目录前缀;占位说明(以 "(" 开头)原样输出。
    read_items = [r if r.startswith("(") else f".specs/{feature}/{r}" for r in reads]
    lines.append(f"下一站  : {skill}")
    lines.append(f"待读    : {', '.join(read_items)}")
    lines.append(f"前置校验: python scripts/flow-guard.py check {feature} {phase}")
    if frozen:
        lines.append(yellow(f"注意    : artifacts.{art}.frozen 已为 true,phase 本应推进到下一站,请检查"))
    return lines


def cmd_status() -> int:
    """报告当前 active feature + phase + 唯一下一站,供跨会话恢复(LINK-109)。"""
    valid, invalid = _scan_features()
    inprogress = [(f, d) for f, d in valid if d.get("phase") != "done"]

    if invalid:
        print(yellow(f"[WARN] state.yaml 异常的 feature(跳过): {', '.join(invalid)}"), file=sys.stderr)
        print(yellow("       Next: 逐个 `python scripts/flow-guard.py validate <feature>` 修复"), file=sys.stderr)

    if not valid:
        print(green("[STATUS] 无 feature(.specs/ 下尚无 state.yaml)。新需求从 flow-router 起。"), file=sys.stderr)
        return 0
    if not inprogress:
        print(green("[STATUS] 无在途 feature(均已 done)。"), file=sys.stderr)
        return 0

    if len(inprogress) == 1:
        f, d = inprogress[0]
        print(green("[STATUS] active feature:"), file=sys.stderr)
        for line in _render_feature(f, d):
            print("  " + line, file=sys.stderr)
        return 0

    # 多个在途:不猜 active,全部列出让用户指明。
    print(yellow(f"[STATUS] 有 {len(inprogress)} 个在途 feature,请指明要继续哪个:"), file=sys.stderr)
    for f, d in inprogress:
        print(yellow(f"  - {f}(phase={d.get('phase')},下一站={STATION.get(d.get('phase'), (None,))[0]})"), file=sys.stderr)
    return 0


def cmd_init(feature: str, lane: str) -> int:
    if lane not in VALID_LANES:
        print(red(f"ERROR: lane 非法: '{lane}',应为 {list(VALID_LANES)}"), file=sys.stderr)
        return 2
    path = _state_path(feature)
    if path.exists():
        print(red(f"ERROR: state.yaml 已存在,拒绝覆盖: {path}"), file=sys.stderr)
        print(yellow("  Next: 直接编辑该文件,或先删除后重新 init"), file=sys.stderr)
        return 2
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(STATE_TEMPLATE.format(feature=feature, lane=lane), encoding="utf-8")
    print(green(f"[INIT] 已创建 {path}(lane={lane})"), file=sys.stderr)
    return 0


def cmd_validate(feature: str) -> int:
    _data, issues = load_state(feature)
    return _print_issues(issues, f"[VALIDATE] state.yaml 通过 schema 校验: {feature}")


def cmd_check(feature: str, phase: str) -> int:
    if phase not in VALID_PHASES:
        print(red(f"ERROR: 未知阶段 '{phase}',应为 {list(VALID_PHASES)}"), file=sys.stderr)
        return 2
    data, schema_issues = load_state(feature)
    # schema 不过先报 schema:状态文件本身坏了,前置判断不可信。
    if any(i.level == "error" for i in schema_issues):
        print(red(f"[CHECK] {feature} → {phase}: state.yaml schema 校验未通过"), file=sys.stderr)
        return _print_issues(schema_issues, "")
    assert data is not None
    issues = list(i for i in schema_issues if i.level == "warning")
    issues.extend(check_preconditions(data, phase))
    return _print_issues(issues, f"[CHECK] 通过:可以进入 '{phase}' 阶段")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Feature 流程阶段门禁(state.yaml + 前置校验)。")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="报告当前 active feature + phase + 下一站(跨会话恢复)")

    p_init = sub.add_parser("init", help="按模板初始化 state.yaml")
    p_init.add_argument("feature")
    p_init.add_argument("--lane", default="L3", help="车道 L2/L3(默认 L3)")

    p_val = sub.add_parser("validate", help="仅做 schema 结构校验")
    p_val.add_argument("feature")

    p_chk = sub.add_parser("check", help="schema + 进入指定阶段的前置条件校验")
    p_chk.add_argument("feature")
    p_chk.add_argument("phase", help=f"目标阶段:{'|'.join(VALID_PHASES)}")

    args = parser.parse_args(argv)

    if args.command == "status":
        return cmd_status()  # 不带 feature 参数,扫描全部

    validate_feature_name(args.feature)

    if args.command == "init":
        return cmd_init(args.feature, args.lane)
    if args.command == "validate":
        return cmd_validate(args.feature)
    if args.command == "check":
        return cmd_check(args.feature, args.phase)
    return 2  # pragma: no cover - argparse required=True 已兜底


if __name__ == "__main__":
    sys.exit(main())
