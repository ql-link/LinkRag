# -*- coding: utf-8 -*-
"""
parser.stability — P0 指标：解析成功率（AggregateMetric）。

metric_id: parser.stability.success_rate
scope:     parse
"""
from __future__ import annotations

from src.evaluation.contracts.metric import MetricResult
from src.evaluation.contracts.evaluable import StageOutput
from src.evaluation.contracts.dataset import EvalSample


class ParserSuccessRate:
    """解析成功率：成功 sample 数 / 总 sample 数。

    AggregateMetric：全数据集收齐后一次性计算。
    high is better = True（越高越好）。
    """

    metric_id = "parser.stability.success_rate"
    scope = "parse"
    higher_is_better = True
    unit = "ratio"

    def compute(
        self,
        outputs: list[StageOutput],
        samples: list[EvalSample],
    ) -> MetricResult:
        """计算解析成功率。

        Args:
            outputs: 所有样本的 parse StageOutput 列表。
            samples: 对应的 EvalSample 列表（此指标不使用 ground_truth）。

        Returns:
            MetricResult: 成功率及失败样本明细。
        """
        total = len(outputs)
        if total == 0:
            return MetricResult(
                metric_id=self.metric_id,
                value=0.0,
                detail={"total": 0, "success": 0, "failed_ids": []},
            )

        failed = [o for o in outputs if not o.success]
        success_count = total - len(failed)

        return MetricResult(
            metric_id=self.metric_id,
            value=round(success_count / total, 4),
            detail={
                "total": total,
                "success": success_count,
                "failed_count": len(failed),
                "failed_ids": [o.sample_id for o in failed],
                "error_types": _count_error_types(failed),
            },
        )


def _count_error_types(failed: list[StageOutput]) -> dict[str, int]:
    """统计失败原因中各异常类型的出现次数。O(n)，n = 失败样本数。"""
    counts: dict[str, int] = {}
    for o in failed:
        key = o.error_type or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts
