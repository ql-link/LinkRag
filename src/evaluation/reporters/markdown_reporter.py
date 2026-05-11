# -*- coding: utf-8 -*-
"""Markdown 格式评估报告渲染器，含文字总结与趋势对比 delta 列。"""
from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING

from .base import BaseReporter

if TYPE_CHECKING:
    from src.evaluation.contracts.store import EvalRun


def _fmt_val(v: object) -> str:
    """格式化指标值为人类可读字符串。"""
    if isinstance(v, float):
        if v < 1.1:
            return f"{v:.2%}"  # 比率类用百分比
        return f"{v:.2f}"
    if isinstance(v, dict):
        return str(v)
    return str(v)


def _fmt_delta(delta: float | None, higher_is_better: bool = True) -> str:
    """格式化 delta 值，正向改善显示 ↑，劣化显示 ↓。"""
    if delta is None:
        return "—"
    symbol = "↑" if (delta > 0) == higher_is_better else "↓"
    return f"{symbol} {abs(delta):.4f}"


_METRIC_LABELS = {
    "parser.md_structure.heading_retention": "标题结构保留率",
    "parser.md_structure.table_retention": "表格结构保留率",
    "parser.md_structure.image_retention": "图片引用保留率",
    "parser.stability.success_rate": "解析成功率",
    "parser.latency.percentiles": "解析耗时分位数",
}


class MarkdownReporter(BaseReporter):
    """将评估结果渲染为 Markdown 报告，支持 baseline delta 对比列。

    输出文件名：{module}_{YYYYMMDDHHMM}.md，存放在 output_dir 目录下。
    报告结构：
    - 元信息表（run_id / 数据集 / 时间 / 样本数）
    - 测试总结（文字描述整体结果）
    - 指标概览（按 metric_id 聚合，便于快速阅读）
    - 指标明细表（metric_id | 值 | delta↑↓）
    - ComparisonGroup 对比矩阵（若存在）
    """

    def render(self, run: "EvalRun", baseline: "EvalRun | None" = None) -> str:
        """渲染 Markdown 报告。

        Args:
            run:      当前评估运行记录。
            baseline: 可选基准运行，有则附加 delta 列。

        Returns:
            str: 输出 Markdown 文件的绝对路径。
        """
        if self.output_dir is None:
            raise ValueError("MarkdownReporter.render 需要 output_dir；远端上传请使用 render_bytes")
        content, _, _ = self.render_bytes(run, baseline)
        run_dt = datetime.fromtimestamp(run.summary.created_at)
        module_name = _module_name(run)
        file_path = os.path.join(self.output_dir, f"{module_name}_{run_dt:%Y%m%d%H%M}.md")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content.decode("utf-8"))

        return os.path.abspath(file_path)

    def render_bytes(self, run: "EvalRun", baseline: "EvalRun | None" = None) -> tuple[bytes, str, str]:
        lines: list[str] = []
        run_dt = datetime.fromtimestamp(run.summary.created_at)
        ts = run_dt.strftime("%Y-%m-%d %H:%M:%S")
        module_name = _module_name(run)
        lines.append("# LinkRag 解析侧评估报告")
        lines.append("")
        lines.append("## 运行信息")
        lines.append("")
        lines.append("| 字段 | 值 |")
        lines.append("|:---|:---|")
        lines.append(f"| Run ID | `{run.summary.run_id}` |")
        lines.append(f"| 测试模块 | {module_name} |")
        lines.append(f"| 数据集 | {run.summary.dataset_name} |")
        lines.append(f"| 评估时间 | {ts} |")
        lines.append(f"| 样本总数 | {run.summary.sample_count} |")
        lines.append(f"| 成功数 | {run.summary.success_count} |")
        if baseline:
            lines.append(f"| 基准 Run ID | `{baseline.summary.run_id}` |")
        lines.append("")

        # ── 测试总结 ──────────────────────────────────────────────────────────
        lines.append("## 测试总结")
        lines.append("")
        lines.extend(_summary_lines(run, module_name, baseline))
        lines.append("")

        # ── 指标概览 ──────────────────────────────────────────────────────────
        lines.append("## 指标概览")
        lines.append("")
        lines.extend(_metric_overview_lines(run.metrics))
        lines.append("")

        # ── 指标明细表 ────────────────────────────────────────────────────────
        lines.append("## 指标明细")
        lines.append("")

        deltas: dict[str, float | None] = {}
        if baseline:
            deltas = self._compute_deltas(run.metrics, baseline.metrics)
            lines.append("| Metric ID | 当前值 | 相对基准 |")
            lines.append("|:---|---:|---:|")
        else:
            lines.append("| Metric ID | 值 |")
            lines.append("|:---|---:|")

        for m in run.metrics:
            mid = m["metric_id"]
            val_str = _fmt_val(m["value"])
            if baseline:
                delta_str = _fmt_delta(deltas.get(mid))
                lines.append(f"| `{mid}` | {val_str} | {delta_str} |")
            else:
                lines.append(f"| `{mid}` | {val_str} |")

        lines.append("")

        # ── ComparisonGroup 对比矩阵 ──────────────────────────────────────────
        for stage_key, stage_result in run.extra.items():
            if not stage_key.startswith("stage_result."):
                continue
            comparison = stage_result.get("comparison")
            if not comparison:
                continue

            stage_name = stage_key.replace("stage_result.", "")
            lines.append(f"## {stage_name} 对比矩阵")
            lines.append("")
            columns = comparison.get("columns", [])
            header = "| Metric |" + "".join(f" {col} |" for col in columns)
            sep = "|:---|" + "---:|" * len(columns)
            lines.append(header)
            lines.append(sep)

            for mid in comparison.get("rows", []):
                row_cells = comparison.get("cells", {}).get(mid, {})
                row = f"| `{mid}` |"
                for col in columns:
                    cell = row_cells.get(col, {})
                    row += f" {_fmt_val(cell.get('value', '—'))} |"
                lines.append(row)

            lines.append("")

        content = "\n".join(lines)
        return content.encode("utf-8"), "markdown", "text/markdown; charset=utf-8"


def _module_name(run: "EvalRun") -> str:
    """Infer the tested module name from stage results."""
    stages = sorted(
        key.replace("stage_result.", "")
        for key in run.extra
        if key.startswith("stage_result.")
    )
    if stages:
        return "_".join(stages)

    dataset_name = run.summary.dataset_name or "evaluation"
    return dataset_name.replace("-", "_")


def _summary_lines(
    run: "EvalRun",
    module_name: str,
    baseline: "EvalRun | None",
) -> list[str]:
    sample_count = run.summary.sample_count
    success_count = run.summary.success_count
    success_rate = success_count / sample_count if sample_count else 0.0
    status_text = "整体通过" if sample_count and success_count == sample_count else "存在失败样本"

    lines = [
        (
            f"本次测试针对 `{module_name}` 模块，使用 `{run.summary.dataset_name}` 数据集，"
            f"共执行 {sample_count} 个样本，成功 {success_count} 个，"
            f"成功率为 {success_rate:.2%}，结论为：{status_text}。"
        )
    ]

    latency = _first_metric_value(run.metrics, "parser.latency.percentiles")
    if isinstance(latency, dict) and latency:
        p50 = latency.get("p50")
        p95 = latency.get("p95")
        lines.append(
            f"解析耗时方面，P50 为 {_fmt_seconds(p50)}，P95 为 {_fmt_seconds(p95)}。"
        )

    if baseline:
        lines.append(f"本报告已与基准 Run `{baseline.summary.run_id}` 做趋势对比。")

    return lines


def _metric_overview_lines(metrics: list[dict]) -> list[str]:
    if not metrics:
        return ["暂无指标结果。"]

    grouped: dict[str, list[object]] = {}
    for metric in metrics:
        grouped.setdefault(metric["metric_id"], []).append(metric.get("value"))

    lines = ["| 指标 | 概览 |", "|:---|:---|"]
    for metric_id, values in grouped.items():
        numeric_values = [float(v) for v in values if isinstance(v, (int, float))]
        if numeric_values:
            overview = (
                f"平均 {_fmt_val(sum(numeric_values) / len(numeric_values))}，"
                f"最小 {_fmt_val(min(numeric_values))}，"
                f"最大 {_fmt_val(max(numeric_values))}，"
                f"样本数 {len(numeric_values)}"
            )
        elif len(values) == 1:
            overview = _metric_overview_text(metric_id, values[0])
        else:
            overview = f"共 {len(values)} 条结果"
        lines.append(f"| {_metric_label(metric_id)} | {overview} |")

    return lines


def _metric_label(metric_id: str) -> str:
    return _METRIC_LABELS.get(metric_id, metric_id)


def _metric_overview_text(metric_id: str, value: object) -> str:
    if metric_id == "parser.latency.percentiles" and isinstance(value, dict):
        return _latency_overview_text(value)
    return _fmt_val(value)


def _latency_overview_text(value: dict) -> str:
    if not value:
        return "暂无成功样本，无法统计解析耗时。"

    p50 = _fmt_seconds(value.get("p50"))
    p95 = _fmt_seconds(value.get("p95"))
    p99 = _fmt_seconds(value.get("p99"))
    mean = _fmt_seconds(value.get("mean"))
    min_value = _fmt_seconds(value.get("min"))
    max_value = _fmt_seconds(value.get("max"))
    return (
        f"解析耗时中位数为 {p50}，P95 为 {p95}，P99 为 {p99}，"
        f"平均耗时 {mean}，最快 {min_value}，最慢 {max_value}。"
    )


def _fmt_seconds(ms_value: object) -> str:
    if isinstance(ms_value, (int, float)):
        return f"{float(ms_value) / 1000:.2f} 秒"
    return "未知"


def _first_metric_value(metrics: list[dict], metric_id: str) -> object | None:
    for metric in metrics:
        if metric.get("metric_id") == metric_id:
            return metric.get("value")
    return None
