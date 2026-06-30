#!/usr/bin/env python
"""下载 C-MTEB 中文检索评测集并转成 BEIR 格式，供 eval_bm25_recall.py --from-beir 使用。

国内默认走 hf-mirror.com 镜像源加速。把 HuggingFace 上 ``C-MTEB/{dataset}``
（corpus + queries）与 ``C-MTEB/{dataset}-qrels``（人工相关性标注）转成标准 BEIR 目录：

    <out>/corpus.jsonl        {"_id","title","text"}
    <out>/queries.jsonl       {"_id","text"}
    <out>/qrels/test.tsv      query-id<TAB>corpus-id<TAB>score

corpus 通常 10 万级，全量分词评测很慢，``--sample`` 采样到指定规模（相关文档全留 +
随机干扰），用于快速对比 es / qdrant 的召回一致性（采样会抬高 recall 绝对值，但不影响
es-vs-qdrant overlap 这一核心对比）。

可选中文集（C-MTEB）：CovidRetrieval / MedicalRetrieval / EcomRetrieval /
DuRetrieval / CmedqaRetrieval / T2Retrieval / MMarcoRetrieval / VideoRetrieval。

用法：
  python scripts/dev/fetch_cmteb_retrieval.py --dataset CovidRetrieval --sample 10000 \\
      --out /tmp/covid_beir
  python scripts/dev/eval_bm25_recall.py --from-beir /tmp/covid_beir --k 10 --with-es --es-password ***
"""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path


def _download(dataset: str, qrels_split: str):
    from huggingface_hub import hf_hub_download, list_repo_files

    def _pick(repo: str, keyword: str) -> str:
        files = [f for f in list_repo_files(repo, repo_type="dataset") if f.endswith(".parquet")]
        hit = [f for f in files if keyword in f.lower()]
        if not hit:
            raise SystemExit(f"{repo} 里找不到含 '{keyword}' 的 parquet：{files}")
        return hf_hub_download(repo, hit[0], repo_type="dataset")

    repo = f"C-MTEB/{dataset}"
    corpus_f = _pick(repo, "corpus")
    queries_f = _pick(repo, "queries")
    qrels_f = _pick(f"{repo}-qrels", qrels_split)
    return corpus_f, queries_f, qrels_f


def main() -> None:
    ap = argparse.ArgumentParser(description="下载 C-MTEB 中文检索集并转 BEIR 格式")
    ap.add_argument("--dataset", default="CovidRetrieval", help="C-MTEB 检索集名")
    ap.add_argument("--qrels-split", default="dev", help="qrels split（多数中文集是 dev）")
    ap.add_argument("--sample", type=int, default=10000, help="corpus 采样规模（0=全量）")
    ap.add_argument("--out", required=True, help="输出 BEIR 目录")
    ap.add_argument("--mirror", default="https://hf-mirror.com", help="HF 镜像源（空串=用官方）")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if args.mirror:
        os.environ["HF_ENDPOINT"] = args.mirror

    import pyarrow.parquet as pq

    corpus_f, queries_f, qrels_f = _download(args.dataset, args.qrels_split)
    corpus = pq.read_table(corpus_f).to_pylist()
    queries = pq.read_table(queries_f).to_pylist()
    qrels = pq.read_table(qrels_f).to_pylist()

    rel_pids = {r["pid"] for r in qrels}
    if args.sample and len(corpus) > args.sample:
        random.seed(args.seed)
        rel_docs = [c for c in corpus if c["id"] in rel_pids]
        non_rel = [c for c in corpus if c["id"] not in rel_pids]
        random.shuffle(non_rel)
        corpus = rel_docs + non_rel[: max(0, args.sample - len(rel_docs))]

    out = Path(args.out)
    (out / "qrels").mkdir(parents=True, exist_ok=True)
    with open(out / "corpus.jsonl", "w", encoding="utf-8") as f:
        for c in corpus:
            rec = {"_id": c["id"], "title": c.get("title", ""), "text": c["text"]}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with open(out / "queries.jsonl", "w", encoding="utf-8") as f:
        for q in queries:
            f.write(json.dumps({"_id": q["id"], "text": q["text"]}, ensure_ascii=False) + "\n")
    with open(out / "qrels" / "test.tsv", "w", encoding="utf-8") as f:
        f.write("query-id\tcorpus-id\tscore\n")
        for r in qrels:
            f.write(f"{r['qid']}\t{r['pid']}\t{int(float(r['score']))}\n")

    print(f"{args.dataset}: corpus {len(corpus)}（相关 {len(rel_pids)}）、queries {len(queries)}、"
          f"qrels {len(qrels)} → {out}")
    print(f"下一步：python scripts/dev/eval_bm25_recall.py --from-beir {out} --k 10 --with-es --es-password ***")


if __name__ == "__main__":
    main()
