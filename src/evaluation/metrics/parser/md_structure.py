# -*- coding: utf-8 -*-
"""
parser.md_structure — P0 指标：Markdown 结构保留率（SampleMetric）。

分别检查标题层级 / 表格 / 图片是否被保留，
与 ground_truth.markdown 对比，通过正则提取元素数量做比率计算。

指标列表（均为 SampleMetric）：
  - parser.md_structure.heading_retention  标题保留率
  - parser.md_structure.table_retention    表格保留率（未被破坏）
  - parser.md_structure.image_retention    图片引用保留率
"""
from __future__ import annotations

import re

from src.evaluation.contracts.metric import MetricResult
from src.evaluation.contracts.evaluable import StageOutput
from src.evaluation.contracts.dataset import EvalSample


# ─── 正则提取工具 ────────────────────────────────────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,6})\s+", re.MULTILINE)
_TABLE_RE = re.compile(r"^\|.+\|", re.MULTILINE)
_IMAGE_RE = re.compile(r"!\[.*?\]\(.*?\)")


def _count_headings(md: str) -> dict[int, int]:
    """统计各级标题数量。O(n)，n = md 字符数。"""
    counts: dict[int, int] = {}
    for m in _HEADING_RE.finditer(md):
        level = len(m.group(1))
        counts[level] = counts.get(level, 0) + 1
    return counts


def _count_tables(md: str) -> int:
    """统计表格行数（不计分隔行）作为表格质量代理指标。"""
    return len(_TABLE_RE.findall(md))


def _count_images(md: str) -> int:
    """统计图片引用数量。"""
    return len(_IMAGE_RE.findall(md))


def _retention_ratio(actual: int, expected: int) -> float:
    """计算保留率，expected=0 时返回 1.0（不扣分）。"""
    if expected == 0:
        return 1.0
    return min(round(actual / expected, 4), 1.0)


# ─── 标题保留率 ───────────────────────────────────────────────────────────────

class HeadingRetentionMetric:
    """标题层级保留率：产物中各级标题数 / ground_truth 中对应级别标题数的加权平均。

    SampleMetric：逐样本计算，需要 ground_truth.markdown 字段。
    若 ground_truth 不含 markdown，则跳过（返回 value=None 的占位结果）。
    """

    metric_id = "parser.md_structure.heading_retention"
    scope = "parse"
    higher_is_better = True
    unit = "ratio"

    def compute(self, output: StageOutput, sample: EvalSample) -> MetricResult:
        gt_md = sample.ground_truth.get("markdown", "")
        if not gt_md or not output.success or not output.payload:
            return MetricResult(
                metric_id=self.metric_id,
                value=0.0,
                detail={"skipped": True, "reason": "无 ground_truth 或解析失败"},
            )

        gt_counts = _count_headings(gt_md)
        out_counts = _count_headings(output.payload)

        # 逐级别计算保留率，按 ground_truth 中该级别标题数加权平均
        gt_total = sum(gt_counts.values())
        if gt_total == 0:
            return MetricResult(
                metric_id=self.metric_id,
                value=1.0,
                detail={"gt_headings": 0, "note": "基准无标题，视为满分"},
            )

        weighted_sum = 0.0
        for level, gt_cnt in gt_counts.items():
            out_cnt = out_counts.get(level, 0)
            ratio = _retention_ratio(out_cnt, gt_cnt)
            weighted_sum += ratio * gt_cnt

        return MetricResult(
            metric_id=self.metric_id,
            value=round(weighted_sum / gt_total, 4),
            detail={
                "sample_id": sample.sample_id,
                "gt_heading_counts": gt_counts,
                "out_heading_counts": out_counts,
            },
        )


# ─── 表格保留率 ───────────────────────────────────────────────────────────────

class TableRetentionMetric:
    """表格保留率：产物表格行数 / ground_truth 表格行数。

    用表格行数而非表格块数，对部分渲染（表格行缺失）更敏感。
    SampleMetric。
    """

    metric_id = "parser.md_structure.table_retention"
    scope = "parse"
    higher_is_better = True
    unit = "ratio"

    def compute(self, output: StageOutput, sample: EvalSample) -> MetricResult:
        gt_md = sample.ground_truth.get("markdown", "")
        if not gt_md or not output.success or not output.payload:
            return MetricResult(
                metric_id=self.metric_id,
                value=0.0,
                detail={"skipped": True, "reason": "无 ground_truth 或解析失败"},
            )

        gt_tables = _count_tables(gt_md)
        out_tables = _count_tables(output.payload)

        return MetricResult(
            metric_id=self.metric_id,
            value=_retention_ratio(out_tables, gt_tables),
            detail={
                "sample_id": sample.sample_id,
                "gt_table_rows": gt_tables,
                "out_table_rows": out_tables,
            },
        )


# ─── 图片保留率 ───────────────────────────────────────────────────────────────

class ImageRetentionMetric:
    """图片引用保留率：产物图片引用数 / ground_truth 图片引用数。SampleMetric。"""

    metric_id = "parser.md_structure.image_retention"
    scope = "parse"
    higher_is_better = True
    unit = "ratio"

    def compute(self, output: StageOutput, sample: EvalSample) -> MetricResult:
        gt_md = sample.ground_truth.get("markdown", "")
        if not gt_md or not output.success or not output.payload:
            return MetricResult(
                metric_id=self.metric_id,
                value=0.0,
                detail={"skipped": True, "reason": "无 ground_truth 或解析失败"},
            )

        gt_images = _count_images(gt_md)
        out_images = _count_images(output.payload)

        return MetricResult(
            metric_id=self.metric_id,
            value=_retention_ratio(out_images, gt_images),
            detail={
                "sample_id": sample.sample_id,
                "gt_image_count": gt_images,
                "out_image_count": out_images,
            },
        )
