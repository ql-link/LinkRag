# -*- coding: utf-8 -*-
"""
parser.latency — P0 指标：解析耗时分位数（AggregateMetric）。

metric_id: parser.latency.p50 / parser.latency.p95
scope:     parse
"""
from __future__ import annotations

import statistics

from src.evaluation.contracts.metric import MetricResult
from src.evaluation.contracts.evaluable import StageOutput
from src.evaluation.contracts.dataset import EvalSample


class ParserLatencyPercentiles:
    """解析耗时 P50 / P95 / P99 统计（AggregateMetric）。

    仅统计成功 sample 的耗时，失败 sample 的耗时不纳入分位计算
    （失败时 elapsed_ms 记录的是异常前的耗时，不代表正常路径性能）。
    但会在 detail 中额外报告包含失败 sample 的全量统计供参考。

    metric_id 以 "parser.latency.percentiles" 为 registry key，
    实际结果 value 为包含 p50/p95/p99/mean/min/max 的字典。
    """

    metric_id = "parser.latency.percentiles"
    scope = "parse"
    higher_is_better = False
    unit = "ms"

    def compute(
        self,
        outputs: list[StageOutput],
        samples: list[EvalSample],
    ) -> MetricResult:
        """计算成功样本的耗时分位数。

        Args:
            outputs: 所有样本的 parse StageOutput 列表。
            samples: 对应的 EvalSample 列表（此指标不使用）。

        Returns:
            MetricResult: value 为 {p50, p95, p99, mean, min, max} 字典。
        """
        success_times = [o.elapsed_ms for o in outputs if o.success]
        all_times = [o.elapsed_ms for o in outputs]

        if not success_times:
            return MetricResult(
                metric_id=self.metric_id,
                value={},
                detail={"warning": "无成功样本，无法计算耗时分位"},
            )

        def _percentile(data: list[float], pct: float) -> float:
            """线性插值计算分位数。O(n log n)。"""
            sorted_data = sorted(data)
            n = len(sorted_data)
            idx = (n - 1) * pct / 100
            lo, hi = int(idx), min(int(idx) + 1, n - 1)
            return round(sorted_data[lo] + (sorted_data[hi] - sorted_data[lo]) * (idx - lo), 2)

        p50 = _percentile(success_times, 50)
        p95 = _percentile(success_times, 95)
        p99 = _percentile(success_times, 99)

        return MetricResult(
            metric_id=self.metric_id,
            value={
                "p50": p50,
                "p95": p95,
                "p99": p99,
                "mean": round(statistics.mean(success_times), 2),
                "min": round(min(success_times), 2),
                "max": round(max(success_times), 2),
            },
            detail={
                "success_sample_count": len(success_times),
                "total_sample_count": len(all_times),
                "all_p50": _percentile(all_times, 50) if all_times else None,
                "all_p95": _percentile(all_times, 95) if all_times else None,
            },
        )
