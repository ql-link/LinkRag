# -*- coding: utf-8 -*-
"""
chunker.boundary — P0 指标：跨标题切割率 / 表格被切坏次数 / 代码块被切坏次数。

metric_id:
  - chunker.boundary.cross_heading_rate   跨标题切割率 (AggregateMetric)
  - chunker.boundary.table_break_count    表格被切坏次数 (AggregateMetric)
  - chunker.boundary.code_break_count     代码块被切坏次数 (AggregateMetric)

scope: chunk
"""
from __future__ import annotations

import re

from src.evaluation.contracts.metric import MetricResult
from src.evaluation.contracts.evaluable import StageOutput
from src.evaluation.contracts.dataset import EvalSample

_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|", re.MULTILINE)
_CODE_FENCE_RE = re.compile(r"^```", re.MULTILINE)


def _has_heading(content: str) -> bool:
    return bool(_HEADING_RE.search(content))


def _count_table_rows(content: str) -> int:
    return len(_TABLE_ROW_RE.findall(content))


def _count_code_fences(content: str) -> int:
    """代码围栏数量；奇数说明围栏未成对 → 代码块被切割。"""
    return len(_CODE_FENCE_RE.findall(content))


# ─── 跨标题切割率 ──────────────────────────────────────────────────────────────

class CrossHeadingRateMetric:
    """跨标题切割率：含多个顶级标题的 chunk 数 / 总 chunk 数。

    一个 chunk 内含多个 heading 通常说明分片边界未对齐标题结构。
    AggregateMetric。
    """

    metric_id = "chunker.boundary.cross_heading_rate"
    scope = "chunk"
    higher_is_better = False  # 越低越好
    unit = "ratio"

    def compute(
        self,
        outputs: list[StageOutput],
        samples: list[EvalSample],
    ) -> MetricResult:
        total_chunks = 0
        cross_chunks = 0

        for out in outputs:
            if not out.success or not isinstance(out.payload, list):
                continue
            for chunk in out.payload:
                total_chunks += 1
                headings = _HEADING_RE.findall(chunk.content)
                if len(headings) > 1:
                    cross_chunks += 1

        ratio = round(cross_chunks / total_chunks, 4) if total_chunks else 0.0
        return MetricResult(
            metric_id=self.metric_id,
            value=ratio,
            detail={
                "total_chunks": total_chunks,
                "cross_heading_chunks": cross_chunks,
            },
        )


# ─── 表格被切坏次数 ────────────────────────────────────────────────────────────

class TableBreakCountMetric:
    """表格被切坏次数：含奇数表格行数的 chunk（表格头/体分离）的累计计数。

    简化启发：若某 chunk 含表格行 > 0 但不含分隔行（|---|），视为表格被切入残片。
    AggregateMetric。
    """

    metric_id = "chunker.boundary.table_break_count"
    scope = "chunk"
    higher_is_better = False
    unit = "count"

    _SEP_RE = re.compile(r"^\|[-:| ]+\|", re.MULTILINE)

    def compute(
        self,
        outputs: list[StageOutput],
        samples: list[EvalSample],
    ) -> MetricResult:
        break_count = 0
        total_chunks = 0

        for out in outputs:
            if not out.success or not isinstance(out.payload, list):
                continue
            for chunk in out.payload:
                total_chunks += 1
                has_rows = bool(_TABLE_ROW_RE.search(chunk.content))
                has_sep = bool(self._SEP_RE.search(chunk.content))
                if has_rows and not has_sep:
                    break_count += 1

        return MetricResult(
            metric_id=self.metric_id,
            value=break_count,
            detail={
                "total_chunks": total_chunks,
                "table_fragment_chunks": break_count,
            },
        )


# ─── 代码块被切坏次数 ──────────────────────────────────────────────────────────

class CodeBreakCountMetric:
    """代码块被切坏次数：代码围栏数量为奇数的 chunk 数。

    围栏数奇数意味着开闭围栏不成对，即代码块被切割到两个 chunk 中。
    AggregateMetric。
    """

    metric_id = "chunker.boundary.code_break_count"
    scope = "chunk"
    higher_is_better = False
    unit = "count"

    def compute(
        self,
        outputs: list[StageOutput],
        samples: list[EvalSample],
    ) -> MetricResult:
        break_count = 0
        total_chunks = 0

        for out in outputs:
            if not out.success or not isinstance(out.payload, list):
                continue
            for chunk in out.payload:
                total_chunks += 1
                if _count_code_fences(chunk.content) % 2 != 0:
                    break_count += 1

        return MetricResult(
            metric_id=self.metric_id,
            value=break_count,
            detail={
                "total_chunks": total_chunks,
                "broken_code_block_chunks": break_count,
            },
        )
