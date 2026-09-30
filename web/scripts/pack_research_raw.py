"""把 LinkRag-Eval 的评测原始产物打包为研究页的静态下载资源。

用法：
    python web/scripts/pack_research_raw.py --eval-root <LinkRag-Eval> [--eval-root <另一个 worktree>]

输出到 web/public/research/raw/：
    <reportId>.json         单份报告的原始结果
    README.md               来源、SHA-256、字段说明、缺失项
    linkrag-eval-<日期>.zip 上述全部文件

单源报告按原字节复制；多源报告（r09、r10）包成「派生打包文件」，
保留每个子文件的原始相对路径、SHA-256 与未改动的内容。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import date
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
OUT = WEB / "public" / "research" / "raw"
SCIFACT = "runs/benchmarks/scifact-20260929"

# reportId -> (说明, [原始相对路径...])；多个路径即派生打包
SOURCES: dict[str, tuple[str, list[str]]] = {
    "r13": ("R13 · 前 30 chunk 文本重排", [f"{SCIFACT}/rerank_top30/results.json"]),
    "r12": ("R12 · 对比 WeKnora 原生检索", [f"{SCIFACT}/weknora/comparison.json"]),
    "r11": ("R11 · LambdaMART 排序", [f"{SCIFACT}/ltr/test_comparison.json"]),
    "r10": (
        "R10 · SciFact 三路消融（summary 为召回指标，audit 为延迟 P50/P95）",
        [f"{SCIFACT}/evaluation/summary.json", f"{SCIFACT}/evaluation/audit.json"],
    ),
    "blind-v5": ("Blind v5 生产契约验收", ["runs/golden_v2/blind_v5_20260728/blind/final_result.json"]),
    "blind-v4": ("Blind v4 最终验收", ["runs/golden_v2/blind_v4_20260724/blind/final_result.json"]),
    "r09": (
        "R09 · 多路召回正式对照（仅稠密 / 稠密+BM25 / 三路）",
        [
            "runs/results/route-dense-only-20260704-top10.json",
            "runs/results/route-dense-bm25-20260704-top10.json",
            "runs/results/route-dense-sparse-bm25-20260704-top10.json",
        ],
    ),
    "fusion": ("融合策略对照", ["runs/tuning/fusion_compare_combined_4domain_clean_20260702.json"]),
}

# 页面上有报告、但本机与评测库都找不到原始产物
MISSING = {
    "corpus-size": "运行 20260621-0311-3eb5545-doubao-clean-3way / 20260622-2142-a017e34-doubao-clean-3way-2k",
    "two-vs-three": "运行 20260620-1723-3eb5545-doubao-800-5domain / 20260620-1939-3eb5545-doubao-800-3way",
    "sparse-models": "报告未给出运行 ID",
}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def locate(roots: list[Path], rel: str) -> Path:
    """runs/ 是本地忽略产物，主 checkout 与其它 worktree 可能各有一部分，按顺序查找。"""
    for root in roots:
        p = root / rel
        if p.exists():
            return p
    raise FileNotFoundError(f"{rel} 不在 {', '.join(map(str, roots))} 中")


def build(roots: list[Path]) -> list[tuple[str, str, int, list[tuple[str, str]]]]:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for rid, (title, rels) in SOURCES.items():
        srcs = [(rel, locate(roots, rel)) for rel in rels]
        dst = OUT / f"{rid}.json"
        if len(srcs) == 1:
            dst.write_bytes(srcs[0][1].read_bytes())
        else:
            bundle = {
                "_bundle": {
                    "kind": "derived bundle（派生打包文件，子文件内容未改动）",
                    "report_id": rid,
                    "title": title,
                    "files": [{"path": rel, "sha256": sha256(p)} for rel, p in srcs],
                },
                "files": {rel: json.loads(p.read_text("utf-8")) for rel, p in srcs},
            }
            dst.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", "utf-8")
        rows.append((rid, title, dst.stat().st_size, [(rel, sha256(p)) for rel, p in srcs]))
    return rows


def readme(rows, stamp: str) -> str:
    lines = [
        "# LinkRag 评测原始结果",
        "",
        f"打包日期：{stamp}。来源仓库：LinkRag-Eval @ 0de8488。",
        "",
        "单源报告为原始运行产物的逐字节拷贝；`r09.json`、`r10.json` 为派生打包文件，",
        "`_bundle.files` 记录每个子文件的原始路径与 SHA-256，`files` 下为未改动的原内容。",
        "",
        "## 文件",
        "",
        "| 报告 ID | 报告 | 大小 | 原始路径 | SHA-256 |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for rid, title, size, srcs in rows:
        for i, (rel, h) in enumerate(srcs):
            head = f"`{rid}.json` | {title} | {size:,} B" if i == 0 else " | | "
            lines.append(f"| {head} | `{rel}` | `{h}` |")
    lines += [
        "",
        "## 口径",
        "",
        "- SciFact（r10–r13）：BEIR SciFact 官方包，5,183 篇文档，官方 test 300 题；源文档级计分，",
        "  同一文档的多个 chunk 只计一次；`ndcg_binary@10` 为二值相关度 nDCG。",
        "- r10 延迟：`evaluation/audit.json` 的 `retrieval_elapsed_ms.p50_linear` / `p95_linear`，页面取整毫秒。",
        "- 四域基线（r09、fusion）：combined_4domain_clean，394 题，3,200 chunks；页面保留 4 位小数。",
        "- Blind（blind-v4、blind-v5）：`baseline_mrr` / `ltr_mrr`，页面以百分数保留 2 位。",
        "",
        "## 暂缺",
        "",
        "以下报告的原始产物在当前备份中未找到，页面对应下载按钮为禁用状态：",
        "",
    ]
    lines += [f"- `{rid}`：{note}" for rid, note in MISSING.items()]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-root", type=Path, action="append", required=True, help="LinkRag-Eval 根目录，可重复")
    args = ap.parse_args()
    stamp = date.today().isoformat()
    rows = build([r.expanduser() for r in args.eval_root])
    (OUT / "README.md").write_text(readme(rows, stamp), "utf-8")
    for old in OUT.glob("linkrag-eval-*.zip"):
        old.unlink()
    zpath = OUT / f"linkrag-eval-{stamp}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(OUT / "README.md", "README.md")
        for rid, *_ in rows:
            z.write(OUT / f"{rid}.json", f"{rid}.json")
    for rid, _, size, _ in rows:
        print(f"{rid}.json\t{size:,} B")
    print(f"{zpath.name}\t{zpath.stat().st_size:,} B")


if __name__ == "__main__":
    main()
