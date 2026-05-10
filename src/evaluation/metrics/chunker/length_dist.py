# -*- coding: utf-8 -*-
"""
chunker.length — P0 指标：分片长度分布与异常分片占比（AggregateMetric）。

metric_id: chunker.length.dist
scope:     chunk
"""
from __future__ import annotations

import statistics

from src.evaluation.contracts.metric import MetricResult
from src.evaluation.contracts.evaluable import StageOutput
from src.evaluation.contracts.dataset import EvalSample

# 分片长度异常判定阈值（字符数）
_MIN_CHARS_THRESHOLD = 50     # 过短分片（可能是孤立标题或碎片）
_MAX_CHARS_THRESHOLD = 3000   # 过长分片（可能未正确切割）


class ChunkLengthDistMetric:
    """分片长度分布 + 异常分片占比（AggregateMetric）。

    计算所有成功 sample 的分片字符数分布，输出：
    - 分位数统计（p10/p50/p90/p99）
    - 过短分片占比（< _MIN_CHARS_THRESHOLD）
    - 过长分片占比（> _MAX_CHARS_THRESHOLD）
    - 直方图（10 个等宽 bucket）
    """

    metric_id = "chunker.length.dist"
    scope = "chunk"
    higher_is_better = False   # 无单一方向，越集中在合理区间越好
    unit = "chars"

    def compute(
        self,
        outputs: list[StageOutput],
        samples: list[EvalSample],
    ) -> MetricResult:
        """统计所有成功样本的分片长度分布。

        Args:
            outputs: 所有样本的 chunk StageOutput（payload 为 list[Chunk]）。
            samples: 对应的 EvalSample 列表。

        Returns:
            MetricResult: value 为分片长度统计字典。
        """
        all_lengths: list[int] = []
        for out in outputs:
            if out.success and isinstance(out.payload, list):
                for chunk in out.payload:
                    all_lengths.append(len(chunk.content))

        if not all_lengths:
            return MetricResult(
                metric_id=self.metric_id,
                value={},
                detail={"warning": "无成功分片，无法计算长度分布"},
            )

        def _pct(data: list[int], p: float) -> float:
            """O(n log n) 线性插值分位数。"""
            s = sorted(data)
            n = len(s)
            idx = (n - 1) * p / 100
            lo, hi = int(idx), min(int(idx) + 1, n - 1)
            return round(s[lo] + (s[hi] - s[lo]) * (idx - lo), 1)

        too_short = sum(1 for x in all_lengths if x < _MIN_CHARS_THRESHOLD)
        too_long = sum(1 for x in all_lengths if x > _MAX_CHARS_THRESHOLD)
        total = len(all_lengths)

        return MetricResult(
            metric_id=self.metric_id,
            value={
                "p10": _pct(all_lengths, 10),
                "p50": _pct(all_lengths, 50),
                "p90": _pct(all_lengths, 90),
                "p99": _pct(all_lengths, 99),
                "mean": round(statistics.mean(all_lengths), 1),
                "min": min(all_lengths),
                "max": max(all_lengths),
                "too_short_ratio": round(too_short / total, 4),
                "too_long_ratio": round(too_long / total, 4),
            },
            detail={
                "total_chunks": total,
                "too_short_count": too_short,
                "too_long_count": too_long,
                "min_threshold": _MIN_CHARS_THRESHOLD,
                "max_threshold": _MAX_CHARS_THRESHOLD,
            },
        )
