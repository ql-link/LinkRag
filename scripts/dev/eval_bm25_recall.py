#!/usr/bin/env python
"""可复现的 BM25 召回评测：量化 Qdrant BM25 后端的召回质量，并与 ES 对比。

回答"Qdrant BM25 能否替代 ES 全文检索"需要可复现的指标，而不是一次性的口头数字。
本脚本对同一份语料、同一把 RagFlowTokenizer，分别灌 Qdrant（本项目 BM25 后端）和
（可选）ES（复刻项目 mapping 与 multi_match 查询），算：

- **recall@k / MRR / nDCG@k**：BM25 召回质量（gold = 字面包含 query 词的文档，客观可算）。
- **fine-only 召回率**：只在 fine 段命中（query 词嵌在长词里被细分出）的文档能否被召回，
  直接量化 coarse+fine 双段相对纯 coarse 的覆盖面增益。
- **es-vs-qdrant overlap@k**（--with-es）：两后端 top-k 结果重合度，"能否替代"的最直接证据。

数据源：
  默认           自带合成中文语料 + query（可复现，不依赖外部数据 / CI 可跑）
  --from-db      连 MySQL 读真实 chunk，对每条做 self-retrieval（抽特征词作 query）
  --from-beir D  BEIR 格式集（corpus.jsonl/queries.jsonl/qrels/test.tsv），用人工分级
                 qrels 算 nDCG@k / recall@k（非 self-retrieval，最有说服力）

安全：只连本地（Qdrant 默认 localhost:36333、ES 默认 localhost:9200），用独立 eval
collection / index，跑完即删；绝不连生产，绝不动 kb_bucket_* / 业务 index。

用法：
  python scripts/dev/eval_bm25_recall.py
  python scripts/dev/eval_bm25_recall.py --with-es --es-password ***
  python scripts/dev/eval_bm25_recall.py --from-db --db-password *** --with-es --es-password ***
  python scripts/dev/eval_bm25_recall.py --avgdl-coarse 175 --avgdl-fine 181   # 校准后复评
  python scripts/dev/eval_bm25_recall.py --from-beir ./nfcorpus --k 10 --with-es --es-password ***
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.preprocessor.ragflow_tokenizer import RagFlowTokenizer  # noqa: E402
from src.core.storage.qdrant_bm25.encoder import Bm25SparseEncoder  # noqa: E402
from src.core.storage.qdrant_bm25.store import Bm25Point, QdrantBm25Store  # noqa: E402

K = 5  # 评测 top-k

# ---- 合成语料：政务 / 社保领域，含多字复合词（fine 细分后能产生 fine-only 命中）----
SYNTHETIC_DOCS = [
    "无线网络配置与故障排查指南",
    "有线网络综合布线施工规范",
    "社保退费查询的操作流程说明",
    "城乡居民基本医疗保险报销比例",
    "职工养老保险待遇领取资格条件",
    "失业保险金申领所需材料清单",
    "住房公积金提取办理流程指南",
    "工伤保险认定申请的受理流程",
    "生育保险津贴发放标准与时间",
    "电子社保卡的申领与线上使用",
    "灵活就业人员参保缴费政策解读",
    "医疗费用异地就医直接结算说明",
]
# query 短语；gold 不在此标注，由"字面是否包含 query 词"客观算出。
SYNTHETIC_QUERIES = [
    "网络",
    "社保",
    "保险待遇",
    "退费查询",
    "公积金提取",
    "异地就医结算",
]


@dataclass
class EvalDoc:
    cid: str
    idx: int
    text: str
    ext: str = ""  # 外部 id（BEIR corpus _id，用于对齐 qrels）；合成 / db 模式不用
    coarse: list[str] = field(default_factory=list)
    fine: list[str] = field(default_factory=list)


def tokenize_docs(tok: RagFlowTokenizer, texts: list[str]) -> list[EvalDoc]:
    docs = []
    for i, text in enumerate(texts):
        tk = tok.tokenize(text)
        docs.append(
            EvalDoc(
                cid=str(uuid.uuid4()),
                idx=i,
                text=text,
                coarse=tk.coarse_tokens.split(),
                fine=tk.fine_tokens.split(),
            )
        )
    return docs


def query_terms(tok: RagFlowTokenizer, query: str) -> list[str]:
    """query 侧只取 coarse 词，与召回适配器 Bm25Retriever._tokenize 一致。"""
    return [t for t in tok.tokenize(query).coarse_tokens.split() if t]


def gold_for(qterms: list[str], docs: list[EvalDoc]) -> tuple[set[str], set[str]]:
    """gold(全字面) = 含任一 query 词（coarse∪fine）的 doc；gold_coarse = 仅看 coarse。

    返回 (gold_all, gold_coarse)；gold_all - gold_coarse 即"只 fine 命中"的文档。
    """
    qset = set(qterms)
    gold_all, gold_coarse = set(), set()
    for d in docs:
        if qset & set(d.coarse):
            gold_coarse.add(d.cid)
            gold_all.add(d.cid)
        elif qset & set(d.fine):
            gold_all.add(d.cid)
    return gold_all, gold_coarse


def recall_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    if not gold:
        return float("nan")
    return len(set(ranked[:k]) & gold) / len(gold)


def mrr(ranked: list[str], gold: set[str]) -> float:
    for i, c in enumerate(ranked):
        if c in gold:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 2) for i, c in enumerate(ranked[:k]) if c in gold)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold), k)))
    return dcg / ideal if ideal else float("nan")


def overlap_at_k(a: list[str], b: list[str], k: int) -> float:
    sa, sb = set(a[:k]), set(b[:k])
    union = sa | sb
    return len(sa & sb) / len(union) if union else float("nan")


# ---------------- Qdrant 侧 ----------------
async def run_qdrant(docs: list[EvalDoc], queries: list[list[str]], enc, host, port):
    coll = f"tolink_bm25_eval_{uuid.uuid4().hex[:8]}"
    store = QdrantBm25Store(host=host, port=port, api_key=None, collection_name=coll)
    from qdrant_client import QdrantClient

    try:
        await store.ensure_collection()
        points = [
            Bm25Point(
                chunk_id=d.cid,
                doc_id=d.idx,
                user_id=1,
                dataset_id=1,
                chunk_type="paragraph",
                sparse_vector=enc.encode_document(d.coarse, d.fine),
            )
            for d in docs
        ]
        # 分批 upsert：一次性灌大语料（万级）会让单请求体过大触发 ReadError。
        for j in range(0, len(points), 1000):
            await store.upsert_chunks(points[j : j + 1000])
        rankings = []
        for qterms in queries:
            qvec = enc.encode_query(qterms)
            hits = await store.query(
                query_vector=qvec, user_id=1, dataset_id=1, doc_id=None, type_mult={}, limit=K
            )
            rankings.append([h.chunk_id for h in hits])
        return rankings
    finally:
        QdrantClient(host=host, port=port, api_key=None, https=False).delete_collection(coll)


# ---------------- ES 侧（复刻 src/core/storage/es 的 mapping 与查询）----------------
def run_es(docs: list[EvalDoc], queries: list[list[str]], url, user, password):
    from elasticsearch import Elasticsearch, helpers

    es = Elasticsearch(url, basic_auth=(user, password), request_timeout=30, verify_certs=False)
    index = f"tolink_bm25_eval_{uuid.uuid4().hex[:8]}"
    # mapping 复刻 src/core/storage/es/mapping.py：coarse/fine 均 whitespace analyzer。
    es.indices.create(
        index=index,
        body={
            "settings": {
                "analysis": {
                    "analyzer": {
                        "ws": {"type": "custom", "tokenizer": "whitespace", "filter": ["lowercase"]}
                    }
                }
            },
            "mappings": {
                "properties": {
                    "user_id": {"type": "long"},
                    "dataset_id": {"type": "long"},
                    "coarse_tokens": {"type": "text", "analyzer": "ws"},
                    "fine_tokens": {"type": "text", "analyzer": "ws"},
                }
            },
        },
    )
    try:
        helpers.bulk(
            es,
            [
                {
                    "_index": index,
                    "_id": d.cid,
                    "_source": {
                        "user_id": 1,
                        "dataset_id": 1,
                        "coarse_tokens": " ".join(d.coarse),
                        "fine_tokens": " ".join(d.fine),
                    },
                }
                for d in docs
            ],
            refresh=True,
        )
        rankings = []
        for qterms in queries:
            # 复刻 src/core/storage/es/retrieval.py 的 multi_match（coarse^2 + fine, best_fields）。
            query_dsl = {
                "bool": {
                    "filter": [{"term": {"user_id": 1}}, {"term": {"dataset_id": 1}}],
                    "must": [
                        {
                            "multi_match": {
                                "fields": ["coarse_tokens^2", "fine_tokens"],
                                "query": " ".join(qterms),
                                "type": "best_fields",
                            }
                        }
                    ],
                }
            }
            resp = es.search(index=index, query=query_dsl, size=K)
            rankings.append([h["_id"] for h in resp["hits"]["hits"]])
        return rankings
    finally:
        es.indices.delete(index=index, ignore_unavailable=True)


def load_db_corpus(args) -> tuple[list[str], list[str] | None]:
    """从 MySQL 读真实 chunk content 作语料；query 用 self-retrieval（见 build_queries）。"""
    import pymysql

    conn = pymysql.connect(
        host=args.db_host, port=args.db_port, user=args.db_user,
        password=args.db_password, database=args.db_database,
        connect_timeout=5, read_timeout=30,
    )
    try:
        cur = conn.cursor()
        sql = "SELECT content FROM kb_document_chunk WHERE content IS NOT NULL AND content != ''"
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        cur.execute(sql)
        return [r[0] for r in cur.fetchall()], None
    finally:
        conn.close()


def build_db_queries(docs: list[EvalDoc]) -> list[str]:
    """self-retrieval：对每个 doc 取其最长的 coarse 词作 query（长词更特异）。"""
    qs = []
    for d in docs:
        multi = [t for t in d.coarse if len(t) >= 2]
        if multi:
            qs.append(max(multi, key=len))
    # 去重，控制评测规模
    seen, uniq = set(), []
    for q in qs:
        if q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq


def ndcg_graded(ranked_ext: list[str], rel_map: dict[str, int], k: int) -> float:
    """分级 nDCG@k：gain 用 qrels 相关性分（线性 gain，log2(i+2) 折扣）。"""
    dcg = sum(rel_map.get(c, 0) / math.log2(i + 2) for i, c in enumerate(ranked_ext[:k]))
    ideal = sorted(rel_map.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else float("nan")


def load_beir(beir_dir: str, tok: RagFlowTokenizer, doc_limit: int = 0):
    """读 BEIR 格式（corpus.jsonl / queries.jsonl / qrels/test.tsv）。

    返回 (docs, cid2ext, queries, qrels)：
      docs    : list[EvalDoc]（cid=内部 uuid 作 Qdrant/ES point id，ext=corpus _id）
      cid2ext : {内部 cid: corpus _id}
      queries : list[(qid, coarse_terms)]，只取 test qrels 涉及、分词非空的 query
      qrels   : {qid: {corpus_id: 相关性分}}（只保留语料内、score>0 的文档）
    """
    root = Path(beir_dir)
    docs: list[EvalDoc] = []
    ext2cid: dict[str, str] = {}
    with open(root / "corpus.jsonl", encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            text = f"{o.get('title', '')} {o.get('text', '')}".strip()
            tk = tok.tokenize(text)
            cid = str(uuid.uuid4())
            ext2cid[o["_id"]] = cid
            docs.append(
                EvalDoc(
                    cid=cid, idx=len(docs), text=text, ext=o["_id"],
                    coarse=tk.coarse_tokens.split(), fine=tk.fine_tokens.split(),
                )
            )
            if doc_limit and len(docs) >= doc_limit:
                break
    cid2ext = {c: e for e, c in ext2cid.items()}

    qrels: dict[str, dict[str, int]] = {}
    with open(root / "qrels" / "test.tsv", encoding="utf-8") as f:
        next(f, None)  # 跳过 header 行
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            qid, did, score = parts[0], parts[1], int(float(parts[2]))
            if score > 0 and did in ext2cid:
                qrels.setdefault(qid, {})[did] = score

    qtexts: dict[str, str] = {}
    with open(root / "queries.jsonl", encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            if o["_id"] in qrels:
                qtexts[o["_id"]] = o.get("text", "")
    queries = []
    for qid in qrels:
        qt = query_terms(tok, qtexts.get(qid, ""))
        if qt:
            queries.append((qid, qt))
    return docs, cid2ext, queries, qrels


def run_beir(args, tok: RagFlowTokenizer, enc: Bm25SparseEncoder) -> None:
    """BEIR 评测：用人工分级 qrels 算 nDCG@k / recall@k，并对比 ES。"""
    import asyncio

    docs, cid2ext, queries, qrels = load_beir(args.from_beir, tok, args.doc_limit)
    print(f"BEIR 语料：{len(docs)} 文档，{len(queries)} 个 test query（人工分级 qrels）\n")
    qts = [qt for _, qt in queries]
    q_rank = asyncio.run(run_qdrant(docs, qts, enc, args.qdrant_host, args.qdrant_port))
    es_rank = (
        run_es(docs, qts, args.es_url, args.es_user, args.es_password) if args.with_es else None
    )

    q_rec, q_ndcg, e_rec, e_ndcg, ov = [], [], [], [], []
    for i, (qid, _) in enumerate(queries):
        rel_map = qrels[qid]
        gold = set(rel_map)
        r_ext = [cid2ext[c] for c in q_rank[i]]
        q_rec.append(recall_at_k(r_ext, gold, K))
        q_ndcg.append(ndcg_graded(r_ext, rel_map, K))
        if es_rank is not None:
            e_ext = [cid2ext[c] for c in es_rank[i]]
            e_rec.append(recall_at_k(e_ext, gold, K))
            e_ndcg.append(ndcg_graded(e_ext, rel_map, K))
            ov.append(overlap_at_k(r_ext, e_ext, K))

    def _avg(xs):
        v = [x for x in xs if not math.isnan(x)]
        return sum(v) / len(v) if v else float("nan")

    print(f"汇总（k={K}，{len(queries)} 个 test query，人工分级 qrels）：")
    print(f"  Qdrant  recall@{K}={_avg(q_rec):.3f}  nDCG@{K}={_avg(q_ndcg):.3f}")
    if es_rank is not None:
        print(f"  ES      recall@{K}={_avg(e_rec):.3f}  nDCG@{K}={_avg(e_ndcg):.3f}")
        print(f"  es-vs-qdrant overlap@{K}={_avg(ov):.3f}（top-{K} 结果重合度，越高越接近 ES）")


def main() -> None:
    import asyncio

    ap = argparse.ArgumentParser(description="BM25 召回评测（Qdrant，可选对比 ES）")
    ap.add_argument("--from-db", action="store_true", help="用真实 MySQL chunk 语料（self-retrieval）")
    ap.add_argument("--with-es", action="store_true", help="同时灌 ES 对比 overlap")
    ap.add_argument("--qdrant-host", default="localhost")
    ap.add_argument("--qdrant-port", type=int, default=36333)
    ap.add_argument("--es-url", default="http://localhost:9200")
    ap.add_argument("--es-user", default="elastic")
    ap.add_argument("--es-password", default="")
    ap.add_argument("--db-host", default="127.0.0.1")
    ap.add_argument("--db-port", type=int, default=33306)
    ap.add_argument("--db-user", default="root")
    ap.add_argument("--db-password", default="")
    ap.add_argument("--db-database", default="tolink_rag_db")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--avgdl-coarse", type=float, default=None, help="覆盖 avgdl_coarse（默认走 settings）")
    ap.add_argument("--avgdl-fine", type=float, default=None, help="覆盖 avgdl_fine（默认走 settings）")
    ap.add_argument("--from-beir", metavar="DIR", help="BEIR 格式数据集目录（用人工 qrels 评测）")
    ap.add_argument("--k", type=int, default=5, help="评测 top-k（BEIR 惯例用 10）")
    ap.add_argument("--doc-limit", type=int, default=0, help="BEIR：最多灌多少文档（0=全部）")
    args = ap.parse_args()

    global K
    K = args.k
    tok = RagFlowTokenizer()

    from src.config import settings

    enc = Bm25SparseEncoder(
        k1=settings.BM25_K1,
        b=settings.BM25_B,
        avgdl_coarse=args.avgdl_coarse if args.avgdl_coarse else settings.BM25_AVGDL,
        avgdl_fine=args.avgdl_fine if args.avgdl_fine else settings.BM25_AVGDL_FINE,
        coarse_boost=settings.BM25_COARSE_BOOST,
    )
    print(f"encoder: k1={enc._k1} b={enc._b} avgdl_coarse={enc._avgdl_coarse} "
          f"avgdl_fine={enc._avgdl_fine} coarse_boost={enc._coarse_boost}\n")

    if args.from_beir:
        run_beir(args, tok, enc)
        return

    if args.from_db:
        texts, _ = load_db_corpus(args)
        docs = tokenize_docs(tok, texts)
        raw_queries = build_db_queries(docs)
        print(f"语料：真实 MySQL chunk {len(docs)} 条；self-retrieval query {len(raw_queries)} 个")
    else:
        docs = tokenize_docs(tok, SYNTHETIC_DOCS)
        raw_queries = SYNTHETIC_QUERIES
        print(f"语料：合成 {len(docs)} 条；query {len(raw_queries)} 个")

    queries = [query_terms(tok, q) for q in raw_queries]

    q_rank = asyncio.run(run_qdrant(docs, queries, enc, args.qdrant_host, args.qdrant_port))
    es_rank = run_es(docs, queries, args.es_url, args.es_user, args.es_password) if args.with_es else None

    # 汇总
    recs, mrrs, ndcgs, fine_recs, overlaps = [], [], [], [], []
    print(f"{'query':<16} {'gold':>4} {'fineOnly':>8} {'R@k':>6} {'MRR':>6} {'nDCG':>6}"
          + ("  esR@k  ovlp@k" if args.with_es else ""))
    print("-" * (58 + (16 if args.with_es else 0)))
    for i, (raw, qt) in enumerate(zip(raw_queries, queries)):
        gold_all, gold_coarse = gold_for(qt, docs)
        fine_only = gold_all - gold_coarse
        ranked = q_rank[i]
        r = recall_at_k(ranked, gold_all, K)
        m = mrr(ranked, gold_all)
        n = ndcg_at_k(ranked, gold_all, K)
        fr = recall_at_k(ranked, fine_only, K) if fine_only else float("nan")
        if not math.isnan(r):
            recs.append(r); mrrs.append(m); ndcgs.append(n)
        if not math.isnan(fr):
            fine_recs.append(fr)
        line = (f"{raw[:15]:<16} {len(gold_all):>4} {len(fine_only):>8} "
                f"{r:>6.3f} {m:>6.3f} {n:>6.3f}")
        if args.with_es:
            er = recall_at_k(es_rank[i], gold_all, K)
            ov = overlap_at_k(ranked, es_rank[i], K)
            if not math.isnan(ov):
                overlaps.append(ov)
            line += f"  {er:>5.3f}  {ov:>5.3f}"
        print(line)

    def _avg(xs):
        return sum(xs) / len(xs) if xs else float("nan")

    print("-" * (58 + (16 if args.with_es else 0)))
    print(f"\n汇总（k={K}，{len(recs)} 个有效 query）：")
    print(f"  Qdrant  recall@{K}={_avg(recs):.3f}  MRR={_avg(mrrs):.3f}  nDCG@{K}={_avg(ndcgs):.3f}")
    if fine_recs:
        print(f"  fine-only 文档召回率={_avg(fine_recs):.3f}（{len(fine_recs)} 个 query 含只-fine-命中文档；"
              f"纯 coarse 时这些必为 0）")
    if args.with_es and overlaps:
        print(f"  es-vs-qdrant overlap@{K}={_avg(overlaps):.3f}（top-{K} 结果重合度，越高越接近 ES）")


if __name__ == "__main__":
    main()
