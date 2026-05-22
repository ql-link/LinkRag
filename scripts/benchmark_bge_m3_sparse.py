"""临时评估 BGE-M3 sparse lexical weights 的效率和检索效果。

该脚本不依赖项目数据库或 Qdrant，只用于本地量化模型本身：
- 效率：模型加载耗时、语料编码耗时、查询编码耗时、打分耗时、吞吐。
- 效果：Top-1、Recall@K、MRR@K、nDCG@K，并输出每个 query 的召回明细。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_MODEL_NAME = "BAAI/bge-m3"
DEFAULT_MAX_LENGTH = 8192

# CPU 512-token sparse timing record.
# Environment: Windows, local BAAI/bge-m3, FlagEmbedding, device=cpu, fp16=False.
# Command:
#   .\.venv\Scripts\python.exe scripts/benchmark_bge_m3_sparse.py --cpu-512-timing --local-files-only --repeat 5 --warmup 1
# Latest result:
# 2026-05-19, model=BAAI/bge-m3, local_files_only=True, warmup=1, repeat=5.
# load_seconds=7.663.
# chunk: tokens=512, chars=825, encode=1.501s, 1501.15 ms/chunk, nonzero=136.
# query1: "显卡", tokens=5, encode=0.083s, 82.52 ms/query, nonzero=3.
# query2: "没有 CUDA 的开发机如何用 CPU 跑 BGE-M3 稀疏向量推理并评估耗时？",
#         tokens=32, encode=0.141s, 141.17 ms/query, nonzero=22.


@dataclass(frozen=True, slots=True)
class CorpusItem:
    """定义一条可被检索的测试 chunk。"""

    doc_id: str
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class QueryCase:
    """定义一条查询以及它的相关 chunk。"""

    query_id: str
    query: str
    relevant_doc_ids: tuple[str, ...]
    note: str


@dataclass(slots=True)
class TimerStats:
    """记录一段操作的耗时统计。"""

    total_seconds: float
    count: int

    @property
    def seconds_per_item(self) -> float:
        """计算单条平均耗时。"""

        if self.count <= 0:
            return 0.0
        return self.total_seconds / self.count

    @property
    def items_per_second(self) -> float:
        """计算每秒处理条数。"""

        if self.total_seconds <= 0:
            return 0.0
        return self.count / self.total_seconds


@dataclass(slots=True)
class RankedHit:
    """记录某个 query 下的一条召回结果。"""

    rank: int
    doc_id: str
    title: str
    score: float
    relevant: bool
    nonzero_count: int


@dataclass(slots=True)
class BenchmarkReport:
    """承载一次完整评估的结构化结果。"""

    model_name: str
    device: str
    batch_size: int
    max_length: int
    use_fp16: bool
    top_k: int
    min_weight: float
    load_seconds: float
    corpus_encode: TimerStats
    query_encode: TimerStats
    score_seconds: float
    corpus_nonzero_avg: float
    query_nonzero_avg: float
    corpus: list[CorpusItem]
    queries: list[QueryCase]
    metrics: dict[str, float]
    baseline_metrics: dict[str, float]
    per_query_hits: dict[str, list[RankedHit]]


def main(argv: Sequence[str] | None = None) -> int:
    """解析参数并执行 BGE-M3 sparse benchmark。"""

    args = parse_args(argv)
    if args.cpu_512_timing:
        run_cpu_512_timing(args)
        return 0

    if args.dataset_json:
        corpus, queries = load_dataset(args.dataset_json)
    else:
        corpus = build_default_corpus()
        queries = build_default_queries()

    if args.list_cases:
        print_cases(corpus, queries)
        return 0

    report = run_benchmark(args=args, corpus=corpus, queries=queries)
    print_report(report, top_n=args.top_n, show_cases=not args.hide_cases)
    if args.output_json:
        write_json_report(report, args.output_json)
    return 0


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """读取命令行参数，默认值尽量贴合当前项目 sparse vector 配置。"""

    parser = argparse.ArgumentParser(
        description="Benchmark BGE-M3 sparse lexical weights on a small built-in retrieval set.",
    )
    parser.add_argument(
        "--model-name",
        default=os.getenv("SPARSE_VECTOR_MODEL_NAME", DEFAULT_MODEL_NAME),
        help="Hugging Face model id or local model directory.",
    )
    parser.add_argument(
        "--cache-dir",
        default=os.getenv("SPARSE_VECTOR_MODEL_CACHE_DIR") or None,
        help="Optional Hugging Face cache directory.",
    )
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        default=env_bool("SPARSE_VECTOR_LOCAL_FILES_ONLY", False),
        help="Use only local model files. This avoids network access during benchmark.",
    )
    parser.add_argument(
        "--device",
        default=os.getenv("SPARSE_VECTOR_DEVICE", "auto"),
        help="auto, cpu, cuda, cuda:0, or another torch device string. Precision is derived from this value.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=env_int("SPARSE_VECTOR_BATCH_SIZE", 8),
        help="Batch size for corpus/query encoding.",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=env_int("SPARSE_VECTOR_MAX_LENGTH", DEFAULT_MAX_LENGTH),
        help="Maximum token length passed to BGE-M3.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=0,
        help="Keep only top K lexical weights per vector. 0 means keep all positive weights.",
    )
    parser.add_argument(
        "--min-weight",
        type=float,
        default=0.0,
        help="Drop lexical weights smaller than this threshold.",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="Warmup encode rounds before timing.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=3,
        help="Timed encode rounds. The report uses the median round.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="Number of hits printed for each query.",
    )
    parser.add_argument(
        "--dataset-json",
        type=Path,
        default=None,
        help="Optional benchmark dataset JSON with corpus and queries fields.",
    )
    parser.add_argument(
        "--hide-cases",
        action="store_true",
        help="Do not print corpus/query test cases in the benchmark report.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to write the structured benchmark report.",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="Print the selected corpus/query cases without loading the model.",
    )
    parser.add_argument(
        "--cpu-512-timing",
        action="store_true",
        help="Run a CPU-only timing test with one 512-token chunk and two queries.",
    )
    return parser.parse_args(argv)


def run_cpu_512_timing(args: argparse.Namespace) -> None:
    """运行固定的 CPU 512-token chunk 推理计时，用于评估本地 CPU 路径性能。"""

    validate_args(args)
    device = "cpu"
    use_fp16 = use_fp16_for_device(device)
    max_length = 512

    load_started_at = perf_counter()
    model = load_bge_m3_model(
        model_name=args.model_name,
        cache_dir=args.cache_dir,
        local_files_only=args.local_files_only,
        device=device,
        batch_size=1,
        max_length=max_length,
        use_fp16=use_fp16,
    )
    load_seconds = perf_counter() - load_started_at

    chunk_text, chunk_tokens = build_cpu_512_token_chunk(model.tokenizer)
    query1 = "显卡"
    query2 = "没有 CUDA 的开发机如何用 CPU 跑 BGE-M3 稀疏向量推理并评估耗时？"
    query1_tokens = count_model_tokens(model.tokenizer, query1)
    query2_tokens = count_model_tokens(model.tokenizer, query2)

    warmup_model(
        model=model,
        texts=[chunk_text, query1, query2],
        rounds=args.warmup,
        batch_size=1,
        max_length=max_length,
    )

    chunk_vectors, chunk_timer = timed_encode_best_round(
        model=model,
        texts=[chunk_text],
        repeat=args.repeat,
        batch_size=1,
        max_length=max_length,
        top_k=args.top_k,
        min_weight=args.min_weight,
    )
    query1_vectors, query1_timer = timed_encode_best_round(
        model=model,
        texts=[query1],
        repeat=args.repeat,
        batch_size=1,
        max_length=max_length,
        top_k=args.top_k,
        min_weight=args.min_weight,
    )
    query2_vectors, query2_timer = timed_encode_best_round(
        model=model,
        texts=[query2],
        repeat=args.repeat,
        batch_size=1,
        max_length=max_length,
        top_k=args.top_k,
        min_weight=args.min_weight,
    )

    print("BGE-M3 CPU 512-token Sparse Timing")
    print("=" * 72)
    print(f"model: {args.model_name}")
    print(f"device: {device}, fp16: {use_fp16}, batch_size: 1, max_length: {max_length}")
    print(f"warmup: {args.warmup}, repeat: {args.repeat}, local_files_only: {args.local_files_only}")
    print(f"load_seconds: {load_seconds:.3f}")
    print("")
    print("Inputs:")
    print(f"chunk_tokens: {chunk_tokens}, chunk_chars: {len(chunk_text)}")
    print(f"query1: {query1} | tokens={query1_tokens}")
    print(f"query2: {query2} | tokens={query2_tokens}")
    print("")
    print("Timing:")
    print(
        "chunk_encode: "
        f"{chunk_timer.total_seconds:.3f}s, "
        f"{chunk_timer.seconds_per_item * 1000:.2f} ms/chunk, "
        f"nonzero={len(chunk_vectors[0])}"
    )
    print(
        "query1_encode: "
        f"{query1_timer.total_seconds:.3f}s, "
        f"{query1_timer.seconds_per_item * 1000:.2f} ms/query, "
        f"nonzero={len(query1_vectors[0])}"
    )
    print(
        "query2_encode: "
        f"{query2_timer.total_seconds:.3f}s, "
        f"{query2_timer.seconds_per_item * 1000:.2f} ms/query, "
        f"nonzero={len(query2_vectors[0])}"
    )


def build_cpu_512_token_chunk(tokenizer: Any) -> tuple[str, int]:
    """构造接近 512 tokens 的单个 chunk，并返回文本与实际 token 数。"""

    seed = (
        "本地知识库的向量化任务会读取解析后的 chunk 原文，调用稠密向量模型和 "
        "BGE-M3 稀疏向量模型，随后把同一个 chunk_id 写入 Qdrant。"
        "如果开发机没有可用 CUDA 设备，系统应当显式使用 CPU 推理，"
        "保持 fp16 关闭，并记录模型加载时间、chunk 推理时间、query 推理时间、"
        "非零稀疏维度数量和失败原因。"
        "在具备 NVIDIA RTX 4090 的环境中，CUDA 路径可以启用 fp16 来提升吞吐，"
        "但 CPU 路径仍然使用 fp32，便于在没有显卡的机器上完成开发测试。"
        "检索阶段拿到候选 chunk_id 后，还必须回查 MySQL 中的文档状态、"
        "chunk 状态、dense_vector_status 和 sparse_vector_status，"
        "避免把已经删除、失败或未完成向量化的数据暴露给用户。"
    )
    text = seed
    while count_model_tokens(tokenizer, text) < 520:
        text = f"{text}\n{seed}"

    token_ids = tokenizer(text, truncation=False)["input_ids"]
    best_text = ""
    best_count = 0
    for end in range(512, 0, -1):
        candidate = tokenizer.decode(token_ids[:end], skip_special_tokens=True)
        token_count = count_model_tokens(tokenizer, candidate)
        if token_count == 512:
            return candidate, token_count
        if best_count < token_count < 512:
            best_text = candidate
            best_count = token_count
    return best_text, best_count


def count_model_tokens(tokenizer: Any, text: str) -> int:
    """统计 BGE-M3 tokenizer 对一段文本产生的 token 数量。"""

    return len(tokenizer(text, truncation=False)["input_ids"])


def run_benchmark(
    *,
    args: argparse.Namespace,
    corpus: Sequence[CorpusItem],
    queries: Sequence[QueryCase],
) -> BenchmarkReport:
    """加载模型，编码语料和查询，并计算 sparse 检索指标。"""

    validate_args(args)
    device = resolve_device(args.device)
    use_fp16 = use_fp16_for_device(device)

    load_started_at = perf_counter()
    model = load_bge_m3_model(
        model_name=args.model_name,
        cache_dir=args.cache_dir,
        local_files_only=args.local_files_only,
        device=device,
        batch_size=args.batch_size,
        max_length=args.max_length,
        use_fp16=use_fp16,
    )
    load_seconds = perf_counter() - load_started_at

    texts = [item.text for item in corpus]
    query_texts = [item.query for item in queries]

    warmup_model(
        model=model,
        texts=[texts[0], query_texts[0]],
        rounds=args.warmup,
        batch_size=args.batch_size,
        max_length=args.max_length,
    )

    corpus_vectors, corpus_encode = timed_encode_best_round(
        model=model,
        texts=texts,
        repeat=args.repeat,
        batch_size=args.batch_size,
        max_length=args.max_length,
        top_k=args.top_k,
        min_weight=args.min_weight,
    )
    query_vectors, query_encode = timed_encode_best_round(
        model=model,
        texts=query_texts,
        repeat=args.repeat,
        batch_size=args.batch_size,
        max_length=args.max_length,
        top_k=args.top_k,
        min_weight=args.min_weight,
    )

    score_started_at = perf_counter()
    per_query_hits = rank_all_queries(
        queries=queries,
        corpus=corpus,
        query_vectors=query_vectors,
        corpus_vectors=corpus_vectors,
    )
    score_seconds = perf_counter() - score_started_at

    metrics = compute_metrics(per_query_hits, queries, k_values=(1, 3, 5))
    baseline_hits = run_lexical_baseline(queries=queries, corpus=corpus)
    baseline_metrics = compute_metrics(baseline_hits, queries, k_values=(1, 3, 5))

    return BenchmarkReport(
        model_name=args.model_name,
        device=device,
        batch_size=args.batch_size,
        max_length=args.max_length,
        use_fp16=use_fp16,
        top_k=args.top_k,
        min_weight=args.min_weight,
        load_seconds=load_seconds,
        corpus_encode=corpus_encode,
        query_encode=query_encode,
        score_seconds=score_seconds,
        corpus_nonzero_avg=mean_len(corpus_vectors),
        query_nonzero_avg=mean_len(query_vectors),
        corpus=list(corpus),
        queries=list(queries),
        metrics=metrics,
        baseline_metrics=baseline_metrics,
        per_query_hits=per_query_hits,
    )


def validate_args(args: argparse.Namespace) -> None:
    """校验会直接影响 benchmark 是否可信的参数。"""

    if args.batch_size <= 0:
        raise ValueError("--batch-size must be greater than 0.")
    if args.max_length <= 0:
        raise ValueError("--max-length must be greater than 0.")
    if args.top_k < 0:
        raise ValueError("--top-k must be non-negative.")
    if args.min_weight < 0 or not math.isfinite(args.min_weight):
        raise ValueError("--min-weight must be finite and non-negative.")
    if args.repeat <= 0:
        raise ValueError("--repeat must be greater than 0.")
    if args.warmup < 0:
        raise ValueError("--warmup must be non-negative.")


def load_bge_m3_model(
    *,
    model_name: str,
    cache_dir: str | None,
    local_files_only: bool,
    device: str,
    batch_size: int,
    max_length: int,
    use_fp16: bool,
) -> Any:
    """加载 BGE-M3；local_files_only=True 时不会触发模型下载。"""

    try:
        from FlagEmbedding import BGEM3FlagModel
    except ImportError as exc:
        raise RuntimeError(
            "FlagEmbedding is required. Run: .\\.venv\\Scripts\\python.exe -m pip install -e ."
        ) from exc

    resolved_model = resolve_model_path(
        model_name=model_name,
        cache_dir=cache_dir,
        local_files_only=local_files_only,
    )
    return BGEM3FlagModel(
        str(resolved_model),
        use_fp16=use_fp16,
        devices=device,
        cache_dir=cache_dir,
        batch_size=batch_size,
        passage_max_length=max_length,
        return_dense=False,
        return_sparse=True,
        return_colbert_vecs=False,
    )


def resolve_model_path(
    *,
    model_name: str,
    cache_dir: str | None,
    local_files_only: bool,
) -> str | Path:
    """把本地路径或 Hugging Face 模型名解析为可加载位置。"""

    candidate = Path(model_name)
    if candidate.exists():
        return candidate.resolve()
    if not local_files_only:
        return model_name

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("huggingface_hub is required for --local-files-only.") from exc
    return snapshot_download(
        repo_id=model_name,
        cache_dir=cache_dir,
        local_files_only=True,
    )


def resolve_device(device: str) -> str:
    """解析推理设备；auto 优先 CUDA，失败时回退 CPU。"""

    normalized = (device or "auto").strip().lower()
    if normalized == "auto":
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    if normalized.startswith("cuda"):
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError(f"Requested {device!r}, but torch reports CUDA is unavailable.")
    return device


def use_fp16_for_device(device: str) -> bool:
    """根据解析后的设备决定推理精度，保持和主程序一致。

    Args:
        device: 已解析的 torch device 字符串，如 cpu、cuda 或 cuda:0。

    Returns:
        bool: CUDA 设备返回 True，其它设备返回 False。
    """

    return (device or "").strip().lower().startswith("cuda")


def warmup_model(
    *,
    model: Any,
    texts: Sequence[str],
    rounds: int,
    batch_size: int,
    max_length: int,
) -> None:
    """执行预热推理，降低首轮 CUDA 初始化对统计值的干扰。"""

    for _ in range(rounds):
        encode_sparse(
            model=model,
            texts=texts,
            batch_size=batch_size,
            max_length=max_length,
            top_k=0,
            min_weight=0.0,
        )


def timed_encode_best_round(
    *,
    model: Any,
    texts: Sequence[str],
    repeat: int,
    batch_size: int,
    max_length: int,
    top_k: int,
    min_weight: float,
) -> tuple[list[dict[str, float]], TimerStats]:
    """重复编码多轮，取耗时中位数所在轮次作为结果。"""

    rounds: list[tuple[float, list[dict[str, float]]]] = []
    for _ in range(repeat):
        started_at = perf_counter()
        vectors = encode_sparse(
            model=model,
            texts=texts,
            batch_size=batch_size,
            max_length=max_length,
            top_k=top_k,
            min_weight=min_weight,
        )
        rounds.append((perf_counter() - started_at, vectors))

    durations = [duration for duration, _ in rounds]
    median_duration = statistics.median(durations)
    best_index = min(range(len(rounds)), key=lambda index: abs(rounds[index][0] - median_duration))
    best_duration, best_vectors = rounds[best_index]
    return best_vectors, TimerStats(total_seconds=best_duration, count=len(texts))


def encode_sparse(
    *,
    model: Any,
    texts: Sequence[str],
    batch_size: int,
    max_length: int,
    top_k: int,
    min_weight: float,
) -> list[dict[str, float]]:
    """调用 BGE-M3 输出 lexical_weights，并规整为可点积的稀疏字典。"""

    output = model.encode(
        list(texts),
        batch_size=batch_size,
        max_length=max_length,
        return_dense=False,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    lexical_weights = output.get("lexical_weights") if isinstance(output, Mapping) else None
    if not isinstance(lexical_weights, list):
        raise RuntimeError("BGE-M3 output missing lexical_weights list.")
    if len(lexical_weights) != len(texts):
        raise RuntimeError(
            f"BGE-M3 lexical_weights count mismatch: {len(lexical_weights)} != {len(texts)}."
        )
    return [
        normalize_sparse_weights(weights, top_k=top_k, min_weight=min_weight)
        for weights in lexical_weights
    ]


def normalize_sparse_weights(
    weights: Mapping[Any, Any],
    *,
    top_k: int,
    min_weight: float,
) -> dict[str, float]:
    """过滤和排序 lexical weights；保留字符串 key 以兼容 token id 或 token 文本。"""

    normalized: dict[str, float] = {}
    for raw_key, raw_value in weights.items():
        value = float(raw_value)
        if not math.isfinite(value) or value <= 0 or value < min_weight:
            continue
        key = str(raw_key)
        previous = normalized.get(key)
        if previous is None or value > previous:
            normalized[key] = value

    if top_k > 0 and len(normalized) > top_k:
        items = sorted(normalized.items(), key=lambda item: (-item[1], item[0]))[:top_k]
        normalized = dict(items)
    if not normalized:
        raise RuntimeError("BGE-M3 returned an empty sparse vector after filtering.")
    return normalized


def rank_all_queries(
    *,
    queries: Sequence[QueryCase],
    corpus: Sequence[CorpusItem],
    query_vectors: Sequence[dict[str, float]],
    corpus_vectors: Sequence[dict[str, float]],
) -> dict[str, list[RankedHit]]:
    """对所有 query 进行 sparse 点积打分并排序。"""

    results: dict[str, list[RankedHit]] = {}
    for query, query_vector in zip(queries, query_vectors, strict=True):
        relevant_doc_ids = set(query.relevant_doc_ids)
        scored: list[tuple[float, CorpusItem, dict[str, float]]] = []
        for item, corpus_vector in zip(corpus, corpus_vectors, strict=True):
            scored.append((sparse_dot(query_vector, corpus_vector), item, corpus_vector))
        scored.sort(key=lambda row: (-row[0], row[1].doc_id))
        results[query.query_id] = [
            RankedHit(
                rank=index + 1,
                doc_id=item.doc_id,
                title=item.title,
                score=score,
                relevant=item.doc_id in relevant_doc_ids,
                nonzero_count=len(corpus_vector),
            )
            for index, (score, item, corpus_vector) in enumerate(scored)
        ]
    return results


def sparse_dot(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    """计算两个稀疏向量的点积，自动遍历更短的一侧。"""

    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(index, 0.0) for index, value in left.items())


def compute_metrics(
    per_query_hits: Mapping[str, Sequence[RankedHit]],
    queries: Sequence[QueryCase],
    *,
    k_values: Sequence[int],
) -> dict[str, float]:
    """计算 Top1、Recall@K、MRR@K 和 nDCG@K。"""

    query_map = {query.query_id: query for query in queries}
    metrics: dict[str, float] = {}
    top1_values: list[float] = []
    for hits in per_query_hits.values():
        top1_values.append(1.0 if hits and hits[0].relevant else 0.0)
    metrics["top1_accuracy"] = safe_mean(top1_values)

    for k in k_values:
        recall_values: list[float] = []
        mrr_values: list[float] = []
        ndcg_values: list[float] = []
        for query_id, hits in per_query_hits.items():
            relevant_count = len(query_map[query_id].relevant_doc_ids)
            top_hits = list(hits[:k])
            relevant_hits = [hit for hit in top_hits if hit.relevant]
            recall_values.append(len(relevant_hits) / max(relevant_count, 1))
            mrr_values.append(reciprocal_rank(top_hits))
            ndcg_values.append(ndcg_at_k(top_hits, relevant_count=relevant_count, k=k))
        metrics[f"recall@{k}"] = safe_mean(recall_values)
        metrics[f"mrr@{k}"] = safe_mean(mrr_values)
        metrics[f"ndcg@{k}"] = safe_mean(ndcg_values)
    return metrics


def reciprocal_rank(hits: Sequence[RankedHit]) -> float:
    """计算一组排序结果的 reciprocal rank。"""

    for hit in hits:
        if hit.relevant:
            return 1.0 / hit.rank
    return 0.0


def ndcg_at_k(hits: Sequence[RankedHit], *, relevant_count: int, k: int) -> float:
    """计算二值相关性的 nDCG@K。"""

    dcg = 0.0
    for index, hit in enumerate(hits[:k], start=1):
        gain = 1.0 if hit.relevant else 0.0
        dcg += gain / math.log2(index + 1)

    ideal_relevant = min(relevant_count, k)
    ideal_dcg = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_relevant + 1))
    if ideal_dcg <= 0:
        return 0.0
    return dcg / ideal_dcg


def run_lexical_baseline(
    *,
    queries: Sequence[QueryCase],
    corpus: Sequence[CorpusItem],
) -> dict[str, list[RankedHit]]:
    """运行一个轻量词面基线，帮助观察 BGE-M3 是否超过简单关键词匹配。"""

    corpus_vectors = [simple_lexical_vector(item.text) for item in corpus]
    query_vectors = [simple_lexical_vector(query.query) for query in queries]
    return rank_all_queries(
        queries=queries,
        corpus=corpus,
        query_vectors=query_vectors,
        corpus_vectors=corpus_vectors,
    )


def simple_lexical_vector(text: str) -> dict[str, float]:
    """把文本切成英文词、数字、中文 2-gram/3-gram，作为简单词面基线。"""

    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9]+", lowered)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", lowered)
    for size in (2, 3):
        tokens.extend(
            "".join(chinese_chars[index : index + size])
            for index in range(len(chinese_chars) - size + 1)
        )
    counts = Counter(token for token in tokens if token)
    length = math.sqrt(sum(value * value for value in counts.values())) or 1.0
    return {token: value / length for token, value in counts.items()}


def build_default_corpus() -> list[CorpusItem]:
    """构造覆盖语义扩展、跨语言、缩写和负样本的测试语料。"""

    return [
        CorpusItem(
            doc_id="D01",
            title="向量一致性",
            text=(
                "文档进入索引阶段后，系统会按 chunk 顺序调用 embedding provider，"
                "同时生成 dense representation 和 sparse lexical weights。"
                "只有同一份文档的全部 chunk 都完成模型推理、Qdrant 写入和 MySQL 状态回写，"
                "文件级 vectorizing_status 才能标记为 SUCCESS。"
                "如果任意 chunk 留在 PENDING、FAILED 或 INDEXING 状态，"
                "上层任务不能把该文档暴露为完整可检索资产。"
            ),
        ),
        CorpusItem(
            doc_id="D02",
            title="失败重试",
            text=(
                "向量化流程采用顺序推进和断点恢复策略。"
                "如果某个 chunk 的模型调用、稀疏向量转换或 Qdrant upsert 失败，"
                "系统会记录 failed_chunk_ids、错误码和失败阶段。"
                "下一次重试不应该重新处理已经成功的 chunk，"
                "而是从第一个失败 chunk 继续执行，并在成功后推进后续 chunk。"
                "这种续跑策略用于减少重复模型调用，并降低数据库状态不一致的概率。"
            ),
        ),
        CorpusItem(
            doc_id="D03",
            title="BGE-M3 输入",
            text=(
                "BGE-M3 sparse lexical weights 的输入必须是 chunk 原文。"
                "模型内部会通过自己的 tokenizer 把自然语言文本转换为 token id，"
                "再由 encoder 输出 vocabulary 维度上的 lexical weight。"
                "Elasticsearch analyzer 产生的倒排词项只属于 ES 索引链路，"
                "不能作为 BGE-M3 的前置输入，否则会丢失上下文、顺序、符号和子词结构。"
            ),
        ),
        CorpusItem(
            doc_id="D04",
            title="RTX 4090 本地推理",
            text=(
                "本地开发机安装了一块 NVIDIA RTX 4090，拥有 24GB GDDR6X 显存，"
                "可以通过 CUDA device cuda:0 执行 BGE-M3 推理。"
                "模型加载后建议开启 fp16，以降低显存占用并提升 batch encoding 吞吐。"
                "如果 torch.cuda.is_available 返回 False，脚本应自动回退到 CPU 和 fp32，"
                "但此时延迟会明显升高。"
            ),
        ),
        CorpusItem(
            doc_id="D05",
            title="Qdrant 混合检索",
            text=(
                "Qdrant collection can store dense embeddings and sparse lexical weights "
                "under the same point id. Hybrid retrieval combines semantic vectors, "
                "lexical sparse signals, and optional reranking to improve recall for "
                "queries that contain abbreviations, code identifiers, product names, "
                "or natural language intent. The storage layer should keep point_id equal "
                "to chunk_id so that search candidates can be traced back to MySQL records."
            ),
        ),
        CorpusItem(
            doc_id="D06",
            title="MySQL 回查",
            text=(
                "Qdrant 只负责向量候选召回，不能作为业务真值来源。"
                "检索链路拿到 candidate chunk_id 之后，必须回查 MySQL 中的租户、知识库、"
                "文档状态、chunk 状态和向量状态。"
                "如果记录已被删除、正在删除、解析失败、dense_vector_status 不是 INDEXED，"
                "或者 sparse_vector_status 不是 INDEXED，该候选都必须被过滤。"
                "这一步也用于处理用户范围、set_id 范围和可见性边界。"
            ),
        ),
        CorpusItem(
            doc_id="D07",
            title="财务条款",
            text=(
                "合同编号 ABC-2026 约定了软件交付后的结算安排。"
                "甲方完成验收并签署确认单后，应在十个工作日内支付剩余款项。"
                "如果超过期限仍未付款，乙方可以按照合同总价的每日千分之一收取违约金。"
                "双方还约定，需求变更导致的新增费用不包含在本次尾款中。"
            ),
        ),
        CorpusItem(
            doc_id="D08",
            title="缓存清理",
            text=(
                "Redis cache invalidation should happen after metadata updates, "
                "especially when user configuration, parse task progress, or provider "
                "routing rules change. This chunk is about cache consistency, stale key "
                "cleanup, and message-driven refresh. It is intentionally unrelated to "
                "BGE-M3 inference, Qdrant sparse vectors, or document payment clauses."
            ),
        ),
    ]


def build_default_queries() -> list[QueryCase]:
    """构造每条都有标准答案的查询集，便于直接量化检索效果。"""

    return [
        QueryCase(
            query_id="Q01",
            query="整份文档什么时候才算向量化成功？",
            relevant_doc_ids=("D01",),
            note="验证文档级成功语义。",
        ),
        QueryCase(
            query_id="Q02",
            query="某个 chunk 写 Qdrant 失败以后应该从哪里重跑？",
            relevant_doc_ids=("D02",),
            note="验证失败 chunk 重试语义。",
        ),
        QueryCase(
            query_id="Q03",
            query="BGE-M3 稀疏向量是否要吃 ES 分词 token？",
            relevant_doc_ids=("D03",),
            note="验证模型 tokenizer 与 ES analyzer 边界。",
        ),
        QueryCase(
            query_id="Q04",
            query="how to improve recall with dense and sparse retrieval",
            relevant_doc_ids=("D05",),
            note="验证英文语义查询。",
        ),
        QueryCase(
            query_id="Q05",
            query="本地模型怎么使用显卡和半精度来加速？",
            relevant_doc_ids=("D04",),
            note="验证 GPU/fp16 相关表达，query 有显卡但文档只有 RTX 4090/CUDA。",
        ),
        QueryCase(
            query_id="Q06",
            query="召回结果为什么还要查 MySQL 的 chunk 状态？",
            relevant_doc_ids=("D06",),
            note="验证检索候选状态过滤。",
        ),
        QueryCase(
            query_id="Q07",
            query="ABC-2026 验收后多久支付尾款？",
            relevant_doc_ids=("D07",),
            note="验证编号和细粒度关键词。",
        ),
        QueryCase(
            query_id="Q08",
            query="显卡",
            relevant_doc_ids=("D04",),
            note="单词同义/上下位测试：query 是显卡，文档写 RTX 4090、CUDA、显存。",
        ),
        QueryCase(
            query_id="Q09",
            query="断点续跑",
            relevant_doc_ids=("D02",),
            note="短语同义测试：query 不写失败 chunk，文档描述断点恢复和重试。",
        ),
        QueryCase(
            query_id="Q10",
            query="向量库",
            relevant_doc_ids=("D05",),
            note="术语同义测试：query 是向量库，文档写 Qdrant collection。",
        ),
        QueryCase(
            query_id="Q11",
            query="权限过滤",
            relevant_doc_ids=("D06",),
            note="业务语义测试：query 是权限过滤，文档写租户、set_id、可见性边界。",
        ),
        QueryCase(
            query_id="Q12",
            query="付款延期",
            relevant_doc_ids=("D07",),
            note="合同语义测试：query 不写逾期，文档描述超过期限付款和违约金。",
        ),
    ]


def load_dataset(path: Path) -> tuple[list[CorpusItem], list[QueryCase]]:
    """从 JSON fixture 读取 corpus 和 queries，供不同模型复用同一测试集。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"Dataset must be a JSON object: {path}")

    raw_corpus = payload.get("corpus")
    raw_queries = payload.get("queries")
    if not isinstance(raw_corpus, list):
        raise ValueError(f"Dataset field 'corpus' must be a list: {path}")
    if not isinstance(raw_queries, list):
        raise ValueError(f"Dataset field 'queries' must be a list: {path}")

    corpus = [parse_corpus_item(item, path=path) for item in raw_corpus]
    queries = [parse_query_case(item, path=path) for item in raw_queries]
    validate_dataset(corpus=corpus, queries=queries, path=path)
    return corpus, queries


def parse_corpus_item(item: object, *, path: Path) -> CorpusItem:
    """解析单条 corpus 记录。"""

    if not isinstance(item, Mapping):
        raise ValueError(f"Dataset corpus item must be an object: {path}")
    return CorpusItem(
        doc_id=require_str(item, "doc_id", path),
        title=require_str(item, "title", path),
        text=require_str(item, "text", path),
    )


def parse_query_case(item: object, *, path: Path) -> QueryCase:
    """解析单条 query 记录。"""

    if not isinstance(item, Mapping):
        raise ValueError(f"Dataset query item must be an object: {path}")
    raw_relevant_doc_ids = item.get("relevant_doc_ids")
    if not isinstance(raw_relevant_doc_ids, list) or not raw_relevant_doc_ids:
        raise ValueError(f"Dataset query relevant_doc_ids must be a non-empty list: {path}")
    relevant_doc_ids = tuple(str(value) for value in raw_relevant_doc_ids)
    return QueryCase(
        query_id=require_str(item, "query_id", path),
        query=require_str(item, "query", path),
        relevant_doc_ids=relevant_doc_ids,
        note=require_str(item, "note", path),
    )


def require_str(item: Mapping[str, object], field: str, path: Path) -> str:
    """读取必填字符串字段。"""

    value = item.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Dataset field {field!r} must be a non-empty string: {path}")
    return value


def validate_dataset(
    *,
    corpus: Sequence[CorpusItem],
    queries: Sequence[QueryCase],
    path: Path,
) -> None:
    """校验测试集的 doc_id 和 query_id 唯一性以及答案引用。"""

    doc_ids = [item.doc_id for item in corpus]
    if len(doc_ids) != len(set(doc_ids)):
        raise ValueError(f"Dataset contains duplicate doc_id values: {path}")

    query_ids = [item.query_id for item in queries]
    if len(query_ids) != len(set(query_ids)):
        raise ValueError(f"Dataset contains duplicate query_id values: {path}")

    known_doc_ids = set(doc_ids)
    for query in queries:
        missing = [doc_id for doc_id in query.relevant_doc_ids if doc_id not in known_doc_ids]
        if missing:
            raise ValueError(
                f"Dataset query {query.query_id!r} references unknown doc_id: {missing}"
            )


def mean_len(vectors: Sequence[Mapping[str, float]]) -> float:
    """计算一批稀疏向量的平均非零维度数。"""

    return safe_mean([float(len(vector)) for vector in vectors])


def safe_mean(values: Iterable[float]) -> float:
    """计算平均值，空列表时返回 0。"""

    items = list(values)
    if not items:
        return 0.0
    return sum(items) / len(items)


def print_cases(corpus: Sequence[CorpusItem], queries: Sequence[QueryCase]) -> None:
    """打印内置语料和查询，便于人工确认测试集是否合适。"""

    print("Corpus:")
    for item in corpus:
        print(f"- {item.doc_id} {item.title}: {item.text}")
    print("\nQueries:")
    for query in queries:
        answers = ", ".join(query.relevant_doc_ids)
        print(f"- {query.query_id} -> {answers}: {query.query} ({query.note})")


def print_report(report: BenchmarkReport, *, top_n: int, show_cases: bool = True) -> None:
    """以可读文本打印 benchmark 结果。"""

    print("BGE-M3 Sparse Benchmark")
    print("=" * 72)
    if show_cases:
        print_test_set(report.corpus, report.queries)
    print("\nRuntime:")
    print(f"model: {report.model_name}")
    print(f"device: {report.device}, fp16: {report.use_fp16}, batch_size: {report.batch_size}")
    print(
        f"max_length: {report.max_length}, "
        f"top_k: {report.top_k}, min_weight: {report.min_weight}"
    )
    print(f"load_seconds: {report.load_seconds:.3f}")
    print(
        "corpus_encode: "
        f"{report.corpus_encode.total_seconds:.3f}s, "
        f"{report.corpus_encode.items_per_second:.2f} texts/s, "
        f"{report.corpus_encode.seconds_per_item * 1000:.2f} ms/text"
    )
    print(
        "query_encode: "
        f"{report.query_encode.total_seconds:.3f}s, "
        f"{report.query_encode.items_per_second:.2f} texts/s, "
        f"{report.query_encode.seconds_per_item * 1000:.2f} ms/query"
    )
    print(f"score_seconds: {report.score_seconds:.6f}")
    print(
        f"avg_nonzero: corpus={report.corpus_nonzero_avg:.1f}, "
        f"query={report.query_nonzero_avg:.1f}"
    )
    print("\nMetrics:")
    print_metric_block("bge_m3_sparse", report.metrics)
    print_metric_block("simple_lexical_baseline", report.baseline_metrics)
    print_query_outcome_summary(report.queries, report.per_query_hits)
    print("\nPer-query BGE-M3 sparse hits:")
    for query_id, hits in report.per_query_hits.items():
        print(f"\n{query_id}")
        for hit in hits[:top_n]:
            marker = "*" if hit.relevant else " "
            print(
                f"  {marker} #{hit.rank:<2} {hit.doc_id:<3} "
                f"score={hit.score:.6f} nz={hit.nonzero_count:<4} {hit.title}"
            )


def print_query_outcome_summary(
    queries: Sequence[QueryCase],
    per_query_hits: Mapping[str, Sequence[RankedHit]],
) -> None:
    """打印每条 query 的标准答案排名，便于快速观察失败用例。"""

    print("\nAnswer Ranks:")
    for query in queries:
        hits = per_query_hits.get(query.query_id, [])
        relevant_ranks = [hit.rank for hit in hits if hit.doc_id in query.relevant_doc_ids]
        best_rank = min(relevant_ranks) if relevant_ranks else None
        status = "HIT" if best_rank == 1 else "MISS"
        rank_text = str(best_rank) if best_rank is not None else "not_found"
        answers = ",".join(query.relevant_doc_ids)
        print(
            f"  {query.query_id:<3} {status:<4} answer={answers:<4} "
            f"best_rank={rank_text:<9} query={query.query}"
        )


def print_test_set(corpus: Sequence[CorpusItem], queries: Sequence[QueryCase]) -> None:
    """打印本次 benchmark 使用的测试语料、查询和标准答案。"""

    print("Test Set:")
    print(f"corpus_size: {len(corpus)}, query_size: {len(queries)}")
    print("\nCorpus Chunks:")
    for item in corpus:
        print(f"  {item.doc_id} [{item.title}] {item.text}")
    print("\nQueries:")
    for query in queries:
        answers = ", ".join(query.relevant_doc_ids)
        print(f"  {query.query_id} answer={answers}")
        print(f"    query: {query.query}")
        print(f"    focus: {query.note}")


def print_metric_block(name: str, metrics: Mapping[str, float]) -> None:
    """打印一组指标，统一保留四位小数。"""

    rendered = ", ".join(f"{key}={value:.4f}" for key, value in metrics.items())
    print(f"  {name}: {rendered}")


def write_json_report(report: BenchmarkReport, path: Path) -> None:
    """把报告写为 JSON，便于后续多轮结果对比。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(report)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\njson_report: {path}")


def env_bool(name: str, default: bool) -> bool:
    """从环境变量读取布尔值。"""

    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    """从环境变量读取整数值。"""

    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


if __name__ == "__main__":
    raise SystemExit(main())
