# -*- coding: utf-8 -*-
"""
BaseEvaluator — 两阶段指标计算基类。

每个 *Evaluator 做四件事：
1. 接收本 stage 所有 sample 的 StageOutput 列表（按 evaluable name 分组）
2. 逐 sample 调用 SampleMetric.compute()
3. 全部收集完毕后调用 AggregateMetric.compute()
4. 若 stage 下注册了多个 evaluable，委托 ComparisonGroup 生成对比矩阵
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.evaluation.contracts.metric import MetricResult
    from src.evaluation.contracts.dataset import EvalSample
    from src.evaluation.contracts.evaluable import StageOutput
    from src.evaluation.metrics.registry import MetricRegistry
    from .comparison import ComparisonMatrix


@dataclass
class EvalStageResult:
    """单个 stage 的完整评估结果。

    Attributes:
        scope:              stage 名称，如 "parse" / "chunk"。
        sample_results:     所有 SampleMetric 对所有样本的计算结果（扁平列表）。
        aggregate_results:  所有 AggregateMetric 的聚合结果列表。
        comparison:         多 evaluable 时的对比矩阵，单 evaluable 时为 None。
    """
    scope: str
    sample_results: list["MetricResult"] = field(default_factory=list)
    aggregate_results: list["MetricResult"] = field(default_factory=list)
    comparison: "ComparisonMatrix | None" = None

    def all_results(self) -> list["MetricResult"]:
        """返回所有指标结果（sample + aggregate）的扁平列表。"""
        return self.sample_results + self.aggregate_results

    def to_dict(self) -> dict:
        """序列化为可 JSON 持久化的字典结构。"""
        def _mr_to_dict(mr: "MetricResult") -> dict:
            return {
                "metric_id": mr.metric_id,
                "value": mr.value,
                "detail": mr.detail,
            }

        return {
            "scope": self.scope,
            "sample_results": [_mr_to_dict(r) for r in self.sample_results],
            "aggregate_results": [_mr_to_dict(r) for r in self.aggregate_results],
            "comparison": self.comparison.to_dict() if self.comparison else None,
        }


class BaseEvaluator:
    """两阶段指标计算基类。

    子类只需声明 scope 属性，其余计算逻辑在基类中统一实现。
    两阶段计算保证：
    - SampleMetric 在每个 sample 完成后即可计算（无需等全量）
    - AggregateMetric 在全量收集后统一计算
    """

    scope: str = ""

    def evaluate(
        self,
        outputs_by_evaluable: dict[str, list["StageOutput"]],
        samples: list["EvalSample"],
        registry: "MetricRegistry",
    ) -> EvalStageResult:
        """执行两阶段指标计算。

        Args:
            outputs_by_evaluable: evaluable_name → 该 evaluable 对所有样本的 StageOutput 列表。
                                  各列表顺序与 samples 一一对应。
            samples:              数据集样本列表，与 outputs 顺序对应。
            registry:             已过滤（include/exclude）后的指标注册表。

        Returns:
            EvalStageResult: 本 stage 的完整评估结果。
        """
        from .comparison import ComparisonGroup

        sample_results: list["MetricResult"] = []
        aggregate_results: list["MetricResult"] = []

        sample_metrics = registry.sample_metrics_for(self.scope)
        aggregate_metrics = registry.aggregate_metrics_for(self.scope)

        # 阶段一：逐样本计算 SampleMetric（O(n × m)，n=样本数，m=指标数）
        for _evaluable_name, outputs in outputs_by_evaluable.items():
            for output, sample in zip(outputs, samples):
                for metric in sample_metrics:
                    try:
                        result = metric.compute(output, sample)
                        sample_results.append(result)
                    except Exception as exc:
                        # 指标自身异常不影响整体评估，记录并跳过
                        import logging
                        logging.getLogger("evaluation").warning(
                            "SampleMetric %s 计算异常，sample=%s: %s",
                            metric.metric_id, sample.sample_id, exc,
                        )

        # 阶段二：全量后调用 AggregateMetric
        for _evaluable_name, outputs in outputs_by_evaluable.items():
            for metric in aggregate_metrics:
                try:
                    result = metric.compute(outputs, samples)
                    aggregate_results.append(result)
                except Exception as exc:
                    import logging
                    logging.getLogger("evaluation").warning(
                        "AggregateMetric %s 计算异常: %s",
                        metric.metric_id, exc,
                    )

        # 阶段三：多 evaluable 时生成对比矩阵
        comparison = None
        if len(outputs_by_evaluable) > 1:
            comparison = ComparisonGroup.build(
                outputs_by_evaluable,
                samples,
                registry,
                self.scope,
            )

        return EvalStageResult(
            scope=self.scope,
            sample_results=sample_results,
            aggregate_results=aggregate_results,
            comparison=comparison,
        )
