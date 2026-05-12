# -*- coding: utf-8 -*-
"""Static HTML reporter for parser evaluation."""
from __future__ import annotations

import html
import os
from datetime import datetime
from typing import TYPE_CHECKING

from .base import BaseReporter

if TYPE_CHECKING:
    from src.evaluation.contracts.store import EvalRun


class HtmlReporter(BaseReporter):
    """Render a compact, single-file HTML report."""

    def render(self, run: "EvalRun", baseline: "EvalRun | None" = None) -> str:
        if self.output_dir is None:
            raise ValueError("HtmlReporter.render 需要 output_dir；远端上传请使用 render_bytes")
        content, _, _ = self.render_bytes(run, baseline)
        path = os.path.join(self.output_dir, f"{run.summary.run_id}.html")
        with open(path, "wb") as f:
            f.write(content)
        return os.path.abspath(path)

    def render_bytes(self, run: "EvalRun", baseline: "EvalRun | None" = None) -> tuple[bytes, str, str]:
        model = self._build_view_model(run, baseline)
        content = _render_html(model)
        return content.encode("utf-8"), "html", "text/html; charset=utf-8"

    def _build_view_model(self, run: "EvalRun", baseline: "EvalRun | None" = None) -> dict:
        total_score = _first_metric(run.metrics, "parser.quality.total_score")
        success_rate = _first_metric(run.metrics, "parser.stability.success_rate")
        latency = _first_metric(run.metrics, "parser.latency.percentiles")
        return {
            "run_id": run.summary.run_id,
            "dataset_name": run.summary.dataset_name,
            "status": run.summary.status,
            "created_at": datetime.fromtimestamp(run.summary.created_at).strftime("%Y-%m-%d %H:%M:%S"),
            "sample_count": run.summary.sample_count,
            "success_count": run.summary.success_count,
            "total_score": total_score.get("value") if total_score else "N/A",
            "success_rate": success_rate.get("value") if success_rate else "N/A",
            "latency": latency.get("value") if latency else {},
            "sample_outputs": run.sample_outputs,
            "archives": run.extra.get("archives", {}),
            "parsed_results": run.extra.get("parsed_results", []),
            "reports": run.extra.get("reports", []),
            "baseline_run_id": baseline.summary.run_id if baseline else None,
        }


def _render_html(model: dict) -> str:
    archive_best = model.get("archives", {}).get("best_top3", [])
    archive_worst = model.get("archives", {}).get("worst_top3", [])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>多源文件解析评估报告</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #17202a; }}
    h1, h2 {{ margin: 0 0 16px; }}
    section {{ margin-top: 28px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .card {{ border: 1px solid #d7dde5; border-radius: 8px; padding: 14px; background: #fbfcfe; }}
    .label {{ color: #667085; font-size: 12px; }}
    .value {{ font-size: 22px; font-weight: 650; margin-top: 6px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border: 1px solid #d7dde5; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #eef3f8; }}
    code {{ background: #eef3f8; padding: 2px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>多源文件解析评估报告</h1>
  <p>Run ID: <code>{_e(model["run_id"])}</code> 数据集: <code>{_e(model["dataset_name"])}</code> 时间: {_e(model["created_at"])}</p>
  <section class="grid">
    {_card("状态", model["status"])}
    {_card("样本数", model["sample_count"])}
    {_card("成功数", model["success_count"])}
    {_card("解析器总分", model["total_score"])}
    {_card("成功率", model["success_rate"])}
  </section>
  <section>
    <h2>耗时概览</h2>
    <pre>{_e(model.get("latency", {}))}</pre>
  </section>
  <section>
    <h2>Top 3 复盘材料</h2>
    <h3>最好 Top 3</h3>
    {_archive_table(archive_best)}
    <h3>最差 Top 3</h3>
    {_archive_table(archive_worst)}
  </section>
  <section>
    <h2>解析结果引用</h2>
    {_parsed_table(model.get("parsed_results", []))}
  </section>
  <section>
    <h2>样本明细</h2>
    {_sample_table(model.get("sample_outputs", []))}
  </section>
</body>
</html>"""


def _card(label: str, value) -> str:
    return f'<div class="card"><div class="label">{_e(label)}</div><div class="value">{_e(value)}</div></div>'


def _archive_table(items: list[dict]) -> str:
    if not items:
        return "<p>暂无数据。</p>"
    rows = "".join(
        f"<tr><td>{_e(item.get('rank'))}</td><td>{_e(item.get('sample_id'))}</td>"
        f"<td>{_e(item.get('evaluable_name'))}</td><td>{_e(item.get('sample_quality_score'))}</td>"
        f"<td><code>{_e(item.get('parsed_key', ''))}</code></td></tr>"
        for item in items
    )
    return f"<table><tr><th>排名</th><th>样本</th><th>解析器</th><th>质量分</th><th>解析结果</th></tr>{rows}</table>"


def _parsed_table(items: list[dict]) -> str:
    if not items:
        return "<p>暂无解析结果引用。</p>"
    rows = "".join(
        f"<tr><td>{_e(item.get('sample_id'))}</td><td>{_e(item.get('evaluable_name'))}</td>"
        f"<td><code>{_e(item.get('parsed_markdown_key', ''))}</code></td></tr>"
        for item in items
    )
    return f"<table><tr><th>样本</th><th>解析器</th><th>MinIO Key</th></tr>{rows}</table>"


def _sample_table(items: list[dict]) -> str:
    if not items:
        return "<p>暂无样本明细。</p>"
    rows = "".join(
        f"<tr><td>{_e(item.get('sample_id'))}</td><td>{_e(item.get('evaluable_name'))}</td>"
        f"<td>{_e(item.get('success'))}</td><td>{_e(item.get('elapsed_ms'))}</td>"
        f"<td>{_e(item.get('error_type', ''))}</td></tr>"
        for item in items
    )
    return f"<table><tr><th>样本</th><th>解析器</th><th>成功</th><th>耗时(ms)</th><th>错误</th></tr>{rows}</table>"


def _first_metric(metrics: list[dict], metric_id: str) -> dict | None:
    for metric in metrics:
        if metric.get("metric_id") == metric_id:
            return metric
    return None


def _e(value) -> str:
    return html.escape(str(value))
