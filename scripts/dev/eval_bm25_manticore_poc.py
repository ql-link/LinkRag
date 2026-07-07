#!/usr/bin/env python
"""Manticore Search POC：验证"能否替代 Qdrant 承担 BM25"这件事的两个关键疑问。

背景：讨论 BM25 按 dataset 精确隔离 IDF 时，发现 Qdrant/ES 都做不到"只用查询过滤
就精确复原某个知识库自己的 IDF"，唯一现实的路是物理隔离（一个知识库一个索引）。
Tantivy 曾经是候选，但因为单进程写锁约束已被弃用（见 PR #270），复活它只是把"新建
一套统计基础设施"换成"新建一套写锁协调基础设施"，量级上没有变小。Manticore 是
服务端进程架构，理论上没有这个限制——本脚本用两个真实测试验证这个判断：

1. **并发写入**：多个独立操作系统进程同时往同一张表插入数据，验证是否会出现类似
   Tantivy 的写锁冲突（这是当年淘汰 Tantivy 的直接原因，必须先确认 Manticore 没有
   同样的硬伤，再谈别的）。
2. **recall / nDCG**：复用 eval_bm25_recall.py 里的 BEIR 加载和指标计算逻辑（不重复
   实现打分公式），跟已经跑过的 Qdrant 基线（NFCorpus recall@10=0.156, nDCG@10=0.323，
   来自 issue #297 / PR #270 的历史评测）做同语料对比；同时复刻 eval_bm25_tenant_isolation.py
   的 pooled vs bucketed 设计，验证"一个知识库一张表"在 Manticore 上是否真的能拿到
   干净的 IDF 隔离效果。

安全：只连本地 Manticore（默认 localhost:19306，见 README 里的 docker run 命令），
用独立 poc_* 表名，跑完即删。

用法：
  docker run -d --name manticore_poc -p 19306:9306 -p 19308:9308 \
      --ulimit nofile=65536:65536 manticoresearch/manticore:latest
  python scripts/dev/eval_bm25_manticore_poc.py \
      --nfcorpus-dir /path/to/nfcorpus --noise-dir "/path/to/噪声语料目录"
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import math
import multiprocessing
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR.parents[1]))

# 复用 eval_bm25_recall.py 的语料加载和指标计算，不重复实现 recall/nDCG 公式。
_spec = importlib.util.spec_from_file_location(
    "eval_bm25_recall", _SCRIPT_DIR / "eval_bm25_recall.py"
)
_eval_bm25_recall = importlib.util.module_from_spec(_spec)
sys.modules["eval_bm25_recall"] = _eval_bm25_recall
_spec.loader.exec_module(_eval_bm25_recall)
load_beir = _eval_bm25_recall.load_beir
recall_at_k = _eval_bm25_recall.recall_at_k
ndcg_graded = _eval_bm25_recall.ndcg_graded

from src.core.preprocessor.ragflow_tokenizer import RagFlowTokenizer  # noqa: E402
from src.core.splitter.factory import create_chunking_engine  # noqa: E402

BM25_K1 = 1.2
BM25_B = 0.75


@dataclass
class _NoiseDoc:
    cid: str
    coarse: list[str]


async def _load_noise_corpus(directory: str, tok: RagFlowTokenizer, limit: int) -> list[_NoiseDoc]:
    """跟 eval_bm25_tenant_isolation.py 用同一份真实中文语料，走同一条生产 chunking pipeline。"""

    engine = create_chunking_engine()
    skip_dirs = {".obsidian", ".claude", ".agents", ".git", "assets"}
    docs: list[_NoiseDoc] = []
    for fp in sorted(Path(directory).rglob("*.md")):
        if any(part in skip_dirs for part in fp.parts):
            continue
        try:
            chunks = await engine.aprocess_file(str(fp))
        except Exception:
            continue
        for ch in chunks:
            if not ch.content or not ch.content.strip():
                continue
            tk = tok.tokenize(ch.content)
            coarse = tk.coarse_tokens.split()
            if not coarse:
                continue
            docs.append(_NoiseDoc(cid=str(uuid.uuid4()), coarse=coarse))
            if limit and len(docs) >= limit:
                return docs
    return docs


def _connect(host: str, port: int):
    import pymysql

    return pymysql.connect(host=host, port=port, user="", password="", autocommit=True, connect_timeout=10)


def _create_table(conn, table: str, *, with_tenant: bool = False) -> None:
    cur = conn.cursor()
    cur.execute(f"DROP TABLE IF EXISTS {table}")
    tenant_col = ", tenant string attribute" if with_tenant else ""
    # charset_table 必须显式包含 CJK：Manticore 默认字符集表不认中文字符，会把中文词
    # 当分隔符处理，实测会把"进程/并发写入/测试"这类词整个丢掉，只留数字/英文子串
    # （已踩坑：不加这个配置，中文噪声语料在 Manticore 里基本等于没索引）。
    # RagFlowTokenizer 已经把中文分好词、空格拼接，这里只需要 charset_table 把中文
    # 字符当"可索引字符"，不需要 ngram_chars/ngram_len 做二次切分。
    cur.execute(
        f"CREATE TABLE {table}(chunk_id string, coarse text{tenant_col}) "
        f"morphology='none' index_field_lengths='1' charset_table='non_cjk, chinese'"
    )


def _insert_batch(conn, table: str, docs: list, id_offset: int, *, tenant: str | None = None) -> None:
    cur = conn.cursor()
    for i, d in enumerate(docs):
        if tenant is not None:
            cur.execute(
                f"INSERT INTO {table} (id, chunk_id, coarse, tenant) VALUES (%s,%s,%s,%s)",
                (id_offset + i, d.cid, " ".join(d.coarse), tenant),
            )
        else:
            cur.execute(
                f"INSERT INTO {table} (id, chunk_id, coarse) VALUES (%s,%s,%s)",
                (id_offset + i, d.cid, " ".join(d.coarse)),
            )


def _query_topk(conn, table: str, qterms: list[str], k: int, *, tenant_filter: str | None = None) -> list[str]:
    cur = conn.cursor()
    # Manticore 默认扩展语法是隐式 AND（空格分隔=所有词都要命中），跟 ES/Qdrant 的
    # BM25 OR 语义（任一词命中即打分，命中词越多排名越高）不同，必须显式用 `|` 连接，
    # 否则多词查询几乎全部落空（已实测：7 词查询隐式 AND 下命中数为 0）。
    q = " | ".join(t.replace("'", " ") for t in qterms if t.strip())
    # tenant 过滤必须写进同一条 WHERE，让 Manticore 在搜索阶段就把候选集限定在本租户
    # 范围内再排 top-k；如果先取 top-k 再在客户端过滤，候选池被别的租户的高分文档
    # 挤占，会漏掉排名本该靠前、但被挤到 k 名开外的本租户文档（已实测踩过这个坑）。
    where_tenant = f" AND tenant='{tenant_filter}'" if tenant_filter is not None else ""
    cur.execute(
        f"SELECT chunk_id, WEIGHT() as w FROM {table} WHERE MATCH(%s){where_tenant} "
        f"ORDER BY w DESC LIMIT {k} OPTION ranker=expr('1000*bm25a({BM25_K1},{BM25_B})')",
        (q,),
    )
    return [row[0] for row in cur.fetchall()]


def _avg(xs: list[float]) -> float:
    v = [x for x in xs if not math.isnan(x)]
    return sum(v) / len(v) if v else float("nan")


# ---------------- 测试 1：并发写入（真实多进程，不是多线程）----------------


def _writer_proc(host: str, port: int, table: str, proc_id: int, n_docs: int, result_q) -> None:
    """独立操作系统进程，模拟"多个 app worker 同时往同一个知识库的表里写"。"""

    try:
        conn = _connect(host, port)
        cur = conn.cursor()
        t0 = time.monotonic()
        ok, failed = 0, 0
        for i in range(n_docs):
            try:
                cur.execute(
                    f"INSERT INTO {table} (id, chunk_id, coarse) VALUES (%s,%s,%s)",
                    (proc_id * 100000 + i, f"p{proc_id}-{i}", f"进程{proc_id} 并发写入 测试 词{i % 7}"),
                )
                ok += 1
            except Exception as exc:
                failed += 1
                if failed <= 3:
                    result_q.put(("error_sample", proc_id, str(exc)))
        result_q.put(("done", proc_id, ok, failed, time.monotonic() - t0))
    except Exception as exc:
        result_q.put(("fatal", proc_id, str(exc)))


def run_concurrent_write_test(host: str, port: int, n_procs: int, docs_per_proc: int) -> None:
    print(f"\n{'=' * 60}\n测试 1：并发写入（{n_procs} 个独立进程，每个写 {docs_per_proc} 条，同一张表）\n{'=' * 60}")
    conn = _connect(host, port)
    table = f"poc_concurrent_{uuid.uuid4().hex[:8]}"
    _create_table(conn, table)

    ctx = multiprocessing.get_context("spawn")
    result_q = ctx.Queue()
    procs = [
        ctx.Process(target=_writer_proc, args=(host, port, table, pid, docs_per_proc, result_q))
        for pid in range(n_procs)
    ]
    t0 = time.monotonic()
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)

    total_ok, total_failed = 0, 0
    error_samples = []
    for _ in range(n_procs * docs_per_proc + n_procs * 5):
        if result_q.empty():
            break
        kind, *rest = result_q.get()
        if kind == "done":
            proc_id, ok, failed, dt = rest
            total_ok += ok
            total_failed += failed
            print(f"  进程 {proc_id}: 成功 {ok}，失败 {failed}，耗时 {dt:.2f}s")
        elif kind == "error_sample":
            error_samples.append(rest)
        elif kind == "fatal":
            print(f"  进程 {rest[0]} 致命错误: {rest[1]}")
    wall = time.monotonic() - t0

    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    actual_count = cur.fetchall()[0][0]
    expected = n_procs * docs_per_proc

    print(f"\n  总耗时 {wall:.2f}s，预期写入 {expected} 条，实际成功回执 {total_ok} 条，"
          f"表里实际查到 {actual_count} 条，失败 {total_failed} 条")
    if error_samples:
        print(f"  失败样例（前 {len(error_samples)} 条）：")
        for proc_id, err in error_samples:
            print(f"    进程 {proc_id}: {err}")
    if total_failed == 0 and actual_count == expected:
        print("  结论：并发写入无锁冲突，写入数量与预期完全一致。")
    else:
        print("  结论：出现写入失败或数量不一致，需要进一步排查（见上面的错误样例）。")

    cur.execute(f"DROP TABLE IF EXISTS {table}")


# ---------------- 测试 2：recall / nDCG（NFCorpus，人工分级 qrels）----------------


def run_recall_ndcg_test(host: str, port: int, nfcorpus_dir: str, doc_limit: int, k: int) -> None:
    print(f"\n{'=' * 60}\n测试 2：recall@{k} / nDCG@{k}（NFCorpus，人工分级 qrels）\n{'=' * 60}")
    tok = RagFlowTokenizer()
    docs, cid2ext, queries, qrels = load_beir(nfcorpus_dir, tok, doc_limit)
    print(f"  {len(docs)} 文档，{len(queries)} 个 test query\n")

    conn = _connect(host, port)
    table = f"poc_recall_{uuid.uuid4().hex[:8]}"
    _create_table(conn, table)
    for i in range(0, len(docs), 500):
        _insert_batch(conn, table, docs[i : i + 500], id_offset=i)

    rec, ndcg = [], []
    for qid, qterms in queries:
        rel_map = qrels[qid]
        gold = set(rel_map)
        cid2doc = {d.cid: d for d in docs}
        ranked_cids = _query_topk(conn, table, qterms, k)
        ranked_ext = [cid2ext[c] for c in ranked_cids if c in cid2doc]
        rec.append(recall_at_k(ranked_ext, gold, k))
        ndcg.append(ndcg_graded(ranked_ext, rel_map, k))

    print(f"  Manticore  recall@{k}={_avg(rec):.4f}  nDCG@{k}={_avg(ndcg):.4f}")
    print("  Qdrant 历史基线（PR #270 / issue #297，同一份 NFCorpus）："
          "recall@10=0.156~0.1571  nDCG@10=0.322~0.3245")

    conn.cursor().execute(f"DROP TABLE IF EXISTS {table}")


# ---------------- 测试 3：pooled vs bucketed（IDF 隔离粒度，复刻 eval_bm25_tenant_isolation.py）----------------


async def run_tenant_isolation_test(
    host: str, port: int, nfcorpus_dir: str, noise_dir: str, doc_limit: int, noise_limit: int, k: int
) -> None:
    print(f"\n{'=' * 60}\n测试 3：pooled vs bucketed（一个知识库一张表，IDF 隔离效果）\n{'=' * 60}")
    tok = RagFlowTokenizer()
    docs, cid2ext, queries, qrels = load_beir(nfcorpus_dir, tok, doc_limit)
    print(f"  NFCorpus（评测租户）：{len(docs)} 文档，{len(queries)} 个 test query")

    noise_docs = await _load_noise_corpus(noise_dir, tok, noise_limit)
    print(f"  噪声语料（另一个不相关领域的真实用户）：{len(noise_docs)} 个 chunk\n")

    conn = _connect(host, port)
    pooled_table = f"poc_pooled_{uuid.uuid4().hex[:8]}"
    bucketed_table = f"poc_bucketed_{uuid.uuid4().hex[:8]}"

    # bucketed：NFCorpus 单独一张表，天然只统计自己的 IDF。
    _create_table(conn, bucketed_table)
    for i in range(0, len(docs), 500):
        _insert_batch(conn, bucketed_table, docs[i : i + 500], id_offset=i)

    # pooled：NFCorpus + 噪声语料混进同一张表并各自打上 tenant 标签，模拟"全局共享 IDF"
    # 的旧架构；查询时用原生 WHERE tenant=... 跟 MATCH() 一起过滤，让 Manticore 在搜索
    # 阶段就把候选集限定在本租户范围内再排 top-k——不能先取 top-k 再客户端过滤，那样
    # 噪声语料里排名靠前的文档会把本租户文档挤出候选池，测出方向相反的假结果（已踩坑）。
    _create_table(conn, pooled_table, with_tenant=True)
    for i in range(0, len(docs), 500):
        _insert_batch(conn, pooled_table, docs[i : i + 500], id_offset=i, tenant="nfcorpus")
    for i in range(0, len(noise_docs), 500):
        _insert_batch(conn, pooled_table, noise_docs[i : i + 500], id_offset=100000 + i, tenant="noise")

    bucketed_rec, bucketed_ndcg = [], []
    pooled_rec, pooled_ndcg = [], []
    for qid, qterms in queries:
        rel_map = qrels[qid]
        gold = set(rel_map)

        b_cids = _query_topk(conn, bucketed_table, qterms, k)
        b_ext = [cid2ext[c] for c in b_cids]
        bucketed_rec.append(recall_at_k(b_ext, gold, k))
        bucketed_ndcg.append(ndcg_graded(b_ext, rel_map, k))

        p_cids = _query_topk(conn, pooled_table, qterms, k, tenant_filter="nfcorpus")
        p_ext = [cid2ext[c] for c in p_cids]
        pooled_rec.append(recall_at_k(p_ext, gold, k))
        pooled_ndcg.append(ndcg_graded(p_ext, rel_map, k))

    print(f"评测结果（k={k}，{len(queries)} 个 query，人工分级 qrels）：")
    print(f"  pooled   (全局共享 IDF，混入噪声语料) recall@{k}={_avg(pooled_rec):.4f}  nDCG@{k}={_avg(pooled_ndcg):.4f}")
    print(f"  bucketed (一个知识库一张表，IDF 只看自己) recall@{k}={_avg(bucketed_rec):.4f}  nDCG@{k}={_avg(bucketed_ndcg):.4f}")
    rec_delta = _avg(bucketed_rec) - _avg(pooled_rec)
    ndcg_delta = _avg(bucketed_ndcg) - _avg(pooled_ndcg)
    print(f"\n  Δrecall@{k} = {rec_delta:+.4f}   ΔnDCG@{k} = {ndcg_delta:+.4f}")
    print("  对照：Qdrant 侧同类测试（issue #297）Δrecall@10=-0.0012  ΔnDCG@10=-0.0003")

    conn.cursor().execute(f"DROP TABLE IF EXISTS {pooled_table}")
    conn.cursor().execute(f"DROP TABLE IF EXISTS {bucketed_table}")


# ---------------- 测试 4：按 dataset 动态算 avgdl（同一张表，dataset_id 属性过滤）----------------


def _query_topk_with_avgdl(conn, table: str, qterms: list[str], k: int, avgdl: float, dataset_filter: int | None) -> list[str]:
    cur = conn.cursor()
    q = " | ".join(t.replace("'", " ") for t in qterms if t.strip())
    where_ds = f" AND dataset_id={dataset_filter}" if dataset_filter is not None else ""
    cur.execute(
        f"SELECT chunk_id, WEIGHT() as w FROM {table} WHERE MATCH(%s){where_ds} "
        f"ORDER BY w DESC LIMIT {k} OPTION ranker=expr('1000*bm25a({BM25_K1},{BM25_B},{avgdl})')",
        (q,),
    )
    return [row[0] for row in cur.fetchall()]


async def run_dataset_scoped_avgdl_test(
    host: str, port: int, nfcorpus_dir: str, noise_dir: str, doc_limit: int, noise_limit: int, k: int
) -> None:
    """同一张表里混两个 dataset，比较全表动态 avgdl / 冻结常量 / 按 dataset 动态算 三种方式。

    按 dataset 动态算：每次查询先跑一次 ``AVG(coarse_len) WHERE dataset_id=X``，
    拿到这个 dataset 自己的平均长度，再把这个值当第三参数传进 bm25a()，同时用
    ``WHERE dataset_id=X`` 把候选集也限定在这个 dataset 内——统计口径和候选范围
    都精确对应同一个 dataset，不依赖 Manticore 默认的全表平均值。
    """

    print(f"\n{'=' * 60}\n测试 4：按 dataset 动态算 avgdl（同一张表，dataset_id 属性过滤）\n{'=' * 60}")
    tok = RagFlowTokenizer()
    docs, cid2ext, queries, qrels = load_beir(nfcorpus_dir, tok, doc_limit)
    noise_docs = await _load_noise_corpus(noise_dir, tok, noise_limit)
    print(f"  dataset 1（NFCorpus）：{len(docs)} 文档；dataset 2（噪声语料）：{len(noise_docs)} chunk\n")

    conn = _connect(host, port)
    cur = conn.cursor()
    table = f"poc_dsavgdl_{uuid.uuid4().hex[:8]}"
    cur.execute(f"DROP TABLE IF EXISTS {table}")
    cur.execute(
        f"CREATE TABLE {table}(chunk_id string, coarse text, dataset_id int) "
        f"morphology='none' index_field_lengths='1' charset_table='non_cjk, chinese'"
    )
    for i, d in enumerate(docs):
        cur.execute(f"INSERT INTO {table} (id, chunk_id, coarse, dataset_id) VALUES (%s,%s,%s,1)", (i, d.cid, " ".join(d.coarse)))
    for i, d in enumerate(noise_docs):
        cur.execute(f"INSERT INTO {table} (id, chunk_id, coarse, dataset_id) VALUES (%s,%s,%s,2)", (100000 + i, d.cid, " ".join(d.coarse)))

    cur.execute(f"SELECT AVG(coarse_len) FROM {table}")
    global_avgdl = cur.fetchall()[0][0]
    cur.execute(f"SELECT AVG(coarse_len) FROM {table} WHERE dataset_id=1")
    ds1_avgdl = cur.fetchall()[0][0]
    print(f"  全表平均长度（两个 dataset 混合）: {global_avgdl:.1f}")
    print(f"  dataset 1（NFCorpus）自己的平均长度: {ds1_avgdl:.1f}\n")

    rec_global, ndcg_global = [], []
    rec_frozen, ndcg_frozen = [], []
    rec_scoped, ndcg_scoped = [], []
    extra_lat = []
    for qid, qterms in queries:
        rel_map = qrels[qid]
        gold = set(rel_map)

        # A. 全表动态 avgdl（不管 dataset，混合语料的平均值），候选按 dataset_id 过滤
        g_cids = _query_topk_with_avgdl(conn, table, qterms, k, global_avgdl, dataset_filter=1)
        g_ext = [cid2ext[c] for c in g_cids]
        rec_global.append(recall_at_k(g_ext, gold, k))
        ndcg_global.append(ndcg_graded(g_ext, rel_map, k))

        # B. 冻结常量（项目现在 Qdrant 的做法）
        f_cids = _query_topk_with_avgdl(conn, table, qterms, k, 185.0, dataset_filter=1)
        f_ext = [cid2ext[c] for c in f_cids]
        rec_frozen.append(recall_at_k(f_ext, gold, k))
        ndcg_frozen.append(ndcg_graded(f_ext, rel_map, k))

        # C. 按 dataset 动态算：每次查询先现算这个 dataset 自己的 avgdl
        t0 = time.monotonic()
        cur.execute(f"SELECT AVG(coarse_len) FROM {table} WHERE dataset_id=1")
        this_avgdl = cur.fetchall()[0][0]
        extra_lat.append((time.monotonic() - t0) * 1000)
        s_cids = _query_topk_with_avgdl(conn, table, qterms, k, this_avgdl, dataset_filter=1)
        s_ext = [cid2ext[c] for c in s_cids]
        rec_scoped.append(recall_at_k(s_ext, gold, k))
        ndcg_scoped.append(ndcg_graded(s_ext, rel_map, k))

    extra_lat.sort()
    print(f"评测结果（k={k}，{len(queries)} 个 query，人工分级 qrels，候选范围统一限定在 dataset 1）：")
    print(f"  A. 全表动态 avgdl（混入 dataset 2）      recall@{k}={_avg(rec_global):.4f}  nDCG@{k}={_avg(ndcg_global):.4f}")
    print(f"  B. 冻结常量 avgdl=185（现在 Qdrant 的做法） recall@{k}={_avg(rec_frozen):.4f}  nDCG@{k}={_avg(ndcg_frozen):.4f}")
    print(f"  C. 按 dataset 动态算（每次查询现算）        recall@{k}={_avg(rec_scoped):.4f}  nDCG@{k}={_avg(ndcg_scoped):.4f}")
    print(f"\n  C 方案每次查询多付出的那次 AVG() 聚合查询延迟：p50={extra_lat[len(extra_lat)//2]:.3f}ms  p95={extra_lat[int(len(extra_lat)*0.95)]:.3f}ms")

    cur.execute(f"DROP TABLE IF EXISTS {table}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Manticore POC：并发写入 + recall/nDCG + IDF 隔离粒度")
    ap.add_argument("--nfcorpus-dir", required=True, help="NFCorpus BEIR 格式目录")
    ap.add_argument("--noise-dir", required=True, help="噪声语料目录（另一个不相关领域的 Markdown 语料）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=19306)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--doc-limit", type=int, default=0)
    ap.add_argument("--noise-limit", type=int, default=0)
    ap.add_argument("--concurrent-procs", type=int, default=8)
    ap.add_argument("--concurrent-docs-per-proc", type=int, default=200)
    ap.add_argument("--skip-concurrent", action="store_true")
    ap.add_argument("--skip-recall", action="store_true")
    ap.add_argument("--skip-tenant", action="store_true")
    ap.add_argument("--skip-dataset-avgdl", action="store_true")
    args = ap.parse_args()

    if not args.skip_concurrent:
        run_concurrent_write_test(args.host, args.port, args.concurrent_procs, args.concurrent_docs_per_proc)
    if not args.skip_recall:
        run_recall_ndcg_test(args.host, args.port, args.nfcorpus_dir, args.doc_limit, args.k)
    if not args.skip_tenant:
        asyncio.run(
            run_tenant_isolation_test(
                args.host, args.port, args.nfcorpus_dir, args.noise_dir,
                args.doc_limit, args.noise_limit, args.k,
            )
        )
    if not args.skip_dataset_avgdl:
        asyncio.run(
            run_dataset_scoped_avgdl_test(
                args.host, args.port, args.nfcorpus_dir, args.noise_dir,
                args.doc_limit, args.noise_limit, args.k,
            )
        )


if __name__ == "__main__":
    main()
