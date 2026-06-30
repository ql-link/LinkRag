#!/usr/bin/env python
"""校准 Qdrant BM25 后端的 avgdl（coarse / fine token 长度统计）。

背景：Qdrant BM25 后端（路 A）在客户端编码时就把长度归一项写进 sparse value，
``avgdl``（全库平均文档长度）一旦写入即冻结。若配置值（默认 coarse=200 / fine=300）
与真实语料偏离，长度归一会系统性偏，长短 chunk 的相对排序跟着歪。本脚本扫真实语料、
用与索引侧同一把 RagFlowTokenizer 统计实际 coarse / fine token 长度，把拍脑袋常数换成
基于数据的值，缩小漂移。

数据源（二选一）：
  --from-db     连 MySQL 读 ``kb_document_chunk.content``（连接参数见下，默认指向本地）
  --from-files  读目录下所有 .txt / .md，每个文件算一条文档

用法：
  python scripts/dev/calibrate_bm25_avgdl.py --from-db --port 33306 --password ***
  python scripts/dev/calibrate_bm25_avgdl.py --from-files ./corpus --limit 500

输出建议的 BM25_AVGDL / BM25_AVGDL_FINE，写进 .env 即可。注意：avgdl 变更只对
**之后写入**的 chunk 生效，存量需重灌才完全对齐——见 docs/internals。
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.preprocessor.ragflow_tokenizer import RagFlowTokenizer  # noqa: E402


def load_from_db(args: argparse.Namespace) -> list[str]:
    import pymysql

    conn = pymysql.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        database=args.database,
        connect_timeout=5,
        read_timeout=30,
    )
    try:
        cur = conn.cursor()
        sql = "SELECT content FROM kb_document_chunk WHERE content IS NOT NULL AND content != ''"
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        cur.execute(sql)
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def load_from_files(path: str, limit: int) -> list[str]:
    texts: list[str] = []
    for p in sorted(Path(path).rglob("*")):
        if p.is_file() and p.suffix.lower() in (".txt", ".md"):
            texts.append(p.read_text(encoding="utf-8", errors="ignore"))
            if limit and len(texts) >= limit:
                break
    return texts


def _pct(sorted_vals: list[int], q: float) -> int:
    if not sorted_vals:
        return 0
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))]


def _summarize(name: str, lengths: list[int]) -> float:
    if not lengths:
        print(f"  {name}: 无数据")
        return 0.0
    s = sorted(lengths)
    mean = statistics.mean(lengths)
    print(
        f"  {name}: n={len(lengths)} mean={mean:.1f} median={statistics.median(s):.0f} "
        f"p90={_pct(s, 0.9)} p95={_pct(s, 0.95)} min={s[0]} max={s[-1]}"
    )
    return mean


def main() -> None:
    ap = argparse.ArgumentParser(description="校准 BM25 avgdl（coarse / fine token 长度统计）")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-db", action="store_true", help="从 MySQL kb_document_chunk 读语料")
    src.add_argument("--from-files", metavar="DIR", help="从目录读 .txt/.md 语料")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=33306)
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default=os.environ.get("MYSQL_PASSWORD", ""))
    ap.add_argument("--database", default="tolink_rag_db")
    ap.add_argument("--limit", type=int, default=0, help="最多取多少条（0=全部）")
    args = ap.parse_args()

    texts = load_from_db(args) if args.from_db else load_from_files(args.from_files, args.limit)
    if not texts:
        print("没有读到任何文本，退出")
        sys.exit(1)

    tok = RagFlowTokenizer()
    coarse_lens: list[int] = []
    fine_lens: list[int] = []
    for text in texts:
        tk = tok.tokenize(text)
        cl, fl = len(tk.coarse_tokens.split()), len(tk.fine_tokens.split())
        if cl:
            coarse_lens.append(cl)
        if fl:
            fine_lens.append(fl)

    print(f"\n语料：{len(texts)} 条文档")
    avgdl_c = _summarize("coarse", coarse_lens)
    avgdl_f = _summarize("fine  ", fine_lens)
    print("\n建议配置（写入 .env，仅对之后写入的 chunk 生效）：")
    print(f"  BM25_AVGDL={round(avgdl_c)}")
    print(f"  BM25_AVGDL_FINE={round(avgdl_f)}")
    print(f"\n（当前默认 200 / 300；按本语料应调整为 {round(avgdl_c)} / {round(avgdl_f)}）")


if __name__ == "__main__":
    main()
