# -*- coding: utf-8 -*-
"""
CLI 入口：python -m src.evaluation run/compare/report

命令：
  run     --config <pipeline.yaml>  [--dataset <name>]  [--output-dir <dir>]
  report  --run-id <id>             [--format json|markdown]
  list    [--dataset <name>]        [--limit 10]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.evaluation",
        description="LinkRag 解析侧质量评估框架 CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── run ──────────────────────────────────────────────────────────────────
    run_p = subparsers.add_parser("run", help="执行评估 pipeline")
    run_p.add_argument(
        "--config", "-c",
        required=True,
        help="Pipeline YAML 配置文件路径",
    )
    run_p.add_argument(
        "--dataset",
        default=None,
        help="数据集名称（覆盖 Pipeline YAML dataset 字段）",
    )
    run_p.add_argument(
        "--dataset-version",
        default=None,
        help="远端数据集版本（默认 EvalConfig.EVAL_DATASET_DEFAULT_VERSION）",
    )
    run_p.add_argument(
        "--split",
        choices=["test", "validation"],
        default=None,
        help="数据集 split（默认 EvalConfig.EVAL_DATASET_SPLIT）",
    )
    run_p.add_argument(
        "--dataset-dir", "-d",
        default=None,
        help="本地数据集目录（仅 EVAL_DATASET_BACKEND=filesystem 时生效）",
    )
    run_p.add_argument(
        "--output-dir", "-o",
        default=None,
        help="报告输出目录（覆盖 pipeline YAML report.output_dir）",
    )
    run_p.add_argument(
        "--store-dir", "-s",
        default=None,
        help="结果存储目录（覆盖 EvalConfig.EVAL_STORE_DIR）",
    )
    run_p.add_argument(
        "--format", "-f",
        nargs="+",
        choices=["json", "markdown", "html"],
        default=["json", "markdown"],
        help="报告格式（可多选）",
    )
    run_p.add_argument(
        "--parallelism", "-p",
        type=int,
        default=None,
        help="Sample 并发数",
    )

    # ── list ─────────────────────────────────────────────────────────────────
    list_p = subparsers.add_parser("list", help="列出历史运行记录")
    list_p.add_argument("--dataset", default=None, help="按数据集过滤")
    list_p.add_argument("--limit", type=int, default=10, help="最多显示条数")
    list_p.add_argument(
        "--store-dir",
        default=None,
        help="结果存储目录",
    )

    # ── report ────────────────────────────────────────────────────────────────
    report_p = subparsers.add_parser("report", help="从已有 run 重新生成报告")
    report_p.add_argument("--run-id", required=True, help="Run ID")
    report_p.add_argument(
        "--format", "-f",
        nargs="+",
        choices=["json", "markdown", "html"],
        default=["markdown"],
    )
    report_p.add_argument("--output-dir", default=None)
    report_p.add_argument("--store-dir", default=None)

    return parser


async def _cmd_run(args: argparse.Namespace) -> int:
    """执行 run 命令。"""
    from src.evaluation.adapters.bootstrap import register_builtin_evaluables
    from src.evaluation.config import eval_config
    from src.evaluation.runners.pipeline import EvalPipeline
    from src.evaluation.datasets.factory import DatasetFactory
    from src.evaluation.storage.factory import ResultStoreFactory
    from src.evaluation.reporters.json_reporter import JsonReporter
    from src.evaluation.reporters.markdown_reporter import MarkdownReporter
    from src.evaluation.reporters.html_reporter import HtmlReporter
    from src.evaluation.hooks.logging_hook import LoggingHook
    from src.evaluation.hooks.progress_hook import ProgressHook
    from src.evaluation.runners.runner import EvaluationRunner
    from src.evaluation.metrics.registry import MetricRegistry

    # 注册所有内置指标
    register_builtin_evaluables()
    _register_builtin_metrics()

    pipeline = EvalPipeline.from_yaml(args.config)

    # CLI 参数覆盖 pipeline/config 值
    if args.parallelism:
        pipeline.runner_cfg.parallelism = args.parallelism
    output_dir = args.output_dir or pipeline.report_cfg.output_dir
    dataset_name = args.dataset or pipeline.dataset_name
    dataset_version = args.dataset_version or pipeline.dataset_version
    dataset_split = args.split or pipeline.dataset_split
    dataset = DatasetFactory.create(
        dataset_name=dataset_name,
        version=dataset_version,
        split=dataset_split,
        dataset_dir=args.dataset_dir,
    )

    # 构建 Reporter 列表
    reporters = []
    for fmt in args.format:
        if fmt == "json":
            reporters.append(JsonReporter(output_dir=None))
        elif fmt == "markdown":
            reporters.append(MarkdownReporter(output_dir=None))
        elif fmt == "html":
            reporters.append(HtmlReporter(output_dir=None))

    # 构建 Hook 列表
    hooks = [LoggingHook(), ProgressHook()]

    store = ResultStoreFactory.create()
    runner = EvaluationRunner(
        pipeline=pipeline,
        dataset=dataset,
        store=store,
        reporters=reporters,
        hooks=hooks,
        metric_registry=MetricRegistry,
    )

    result = await runner.run()
    print(f"\n✅ 评估完成: run_id={result.summary.run_id}")
    print(f"   样本: {result.summary.sample_count}，成功: {result.summary.success_count}")
    print("   报告已输出至远端 ResultStore")
    return 0


async def _cmd_list(args: argparse.Namespace) -> int:
    """执行 list 命令。"""
    from src.evaluation.config import eval_config
    from src.evaluation.storage.factory import ResultStoreFactory

    store = ResultStoreFactory.create()

    filters = {}
    if args.dataset:
        filters["dataset_name"] = args.dataset

    runs = await store.list_runs(**filters)
    runs = runs[: args.limit]

    if not runs:
        print("暂无历史运行记录。")
        return 0

    print(f"{'Run ID':<38} {'数据集':<20} {'状态':<10} {'样本':>6} {'成功':>6}")
    print("-" * 85)
    for r in runs:
        from datetime import datetime
        ts = datetime.fromtimestamp(r.created_at).strftime("%m-%d %H:%M")
        print(
            f"{r.run_id:<38} {r.dataset_name:<20} {r.status:<10}"
            f" {r.sample_count:>6} {r.success_count:>6}  {ts}"
        )
    return 0


async def _cmd_report(args: argparse.Namespace) -> int:
    """执行 report 命令（从已有 run 重新渲染报告）。"""
    from src.evaluation.config import eval_config
    from src.evaluation.storage.factory import ResultStoreFactory
    from src.evaluation.reporters.json_reporter import JsonReporter
    from src.evaluation.reporters.markdown_reporter import MarkdownReporter
    from src.evaluation.reporters.html_reporter import HtmlReporter

    output_dir = args.output_dir or eval_config.EVAL_REPORT_DIR
    store = ResultStoreFactory.create()

    run = await store.load_run(args.run_id)
    if run is None:
        print(f"❌ Run '{args.run_id}' 不存在，请用 list 命令查看可用 run。", file=sys.stderr)
        return 1

    baseline = await store.load_baseline(run.summary.dataset_name)
    if baseline and baseline.summary.run_id == run.summary.run_id:
        baseline = None

    for fmt in args.format:
        if fmt == "json":
            path = JsonReporter(output_dir=output_dir).render(run, baseline)
        elif fmt == "markdown":
            path = MarkdownReporter(output_dir=output_dir).render(run, baseline)
        else:
            path = HtmlReporter(output_dir=output_dir).render(run, baseline)
        print(f"✅ 报告已生成: {path}")

    return 0


def _register_builtin_metrics() -> None:
    """注册所有内置指标到全局 MetricRegistry。"""
    from src.evaluation.metrics.registry import MetricRegistry
    from src.evaluation.metrics.parser.stability import ParserSuccessRate
    from src.evaluation.metrics.parser.latency import ParserLatencyPercentiles
    from src.evaluation.metrics.parser.md_structure import (
        HeadingRetentionMetric, TableRetentionMetric, ImageRetentionMetric,
    )
    from src.evaluation.metrics.parser.text_completeness import TextCompletenessMetric
    from src.evaluation.metrics.parser.heading_quality import (
        HeadingCoverageMetric, HeadingLevelAccuracyMetric,
    )
    from src.evaluation.metrics.parser.image_quality import ImageQualityMetric as ParserImageQualityMetric
    from src.evaluation.metrics.parser.table_quality import TableQualityMetric
    from src.evaluation.metrics.parser.quality_score import (
        ParserSampleQualityMetric, ParserTotalScoreMetric, TopSampleRankingMetric,
    )
    from src.evaluation.metrics.chunker.length_dist import ChunkLengthDistMetric
    from src.evaluation.metrics.chunker.boundary import (
        CrossHeadingRateMetric, TableBreakCountMetric, CodeBreakCountMetric,
    )

    # parse scope — AggregateMetric
    MetricRegistry.register_aggregate(ParserSuccessRate())
    MetricRegistry.register_aggregate(ParserLatencyPercentiles())
    # parse scope — SampleMetric
    MetricRegistry.register_sample(HeadingRetentionMetric())
    MetricRegistry.register_sample(TableRetentionMetric())
    MetricRegistry.register_sample(ImageRetentionMetric())
    MetricRegistry.register_sample(TextCompletenessMetric())
    MetricRegistry.register_sample(HeadingCoverageMetric())
    MetricRegistry.register_sample(HeadingLevelAccuracyMetric())
    MetricRegistry.register_sample(ParserImageQualityMetric())
    MetricRegistry.register_sample(TableQualityMetric())
    MetricRegistry.register_sample(ParserSampleQualityMetric())
    MetricRegistry.register_aggregate(ParserTotalScoreMetric())
    MetricRegistry.register_aggregate(TopSampleRankingMetric())
    # chunk scope — AggregateMetric
    MetricRegistry.register_aggregate(ChunkLengthDistMetric())
    MetricRegistry.register_aggregate(CrossHeadingRateMetric())
    MetricRegistry.register_aggregate(TableBreakCountMetric())
    MetricRegistry.register_aggregate(CodeBreakCountMetric())


def main() -> None:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args()

    cmd_map = {
        "run": _cmd_run,
        "list": _cmd_list,
        "report": _cmd_report,
    }

    exit_code = asyncio.run(cmd_map[args.command](args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
