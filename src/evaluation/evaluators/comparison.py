# -*- coding: utf-8 -*-
"""
ComparisonGroup — 同 stage 多 evaluable 横向对比矩阵。

当同一个 stage 注册了多个 evaluable（如 parser.pdf.mineru vs parser.pdf.naive），
自动生成以 metric_id 为行、evaluable_name 为列的对比矩阵。
Reporter 直接消费此矩阵渲染为表格，无需额外逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.evaluation.contracts.metric import MetricResult
    from src.evaluation.contracts.dataset import EvalSample
    from src.evaluation.contracts.evaluable import StageOutput
    from src.evaluation.metrics.registry import MetricRegistry


@dataclass
class ComparisonCell:
    """对比矩阵单元格：某 evaluable 在某 metric 上的结果。

    Attributes:
        metric_id:      指标唯一标识。
        evaluable_name: evaluable 唯一标识。
        value:          指标计算结果值。
        unit:           指标单位。
    """
    metric_id: str
    evaluable_name: str
    value: float | dict | list
    unit: str = ""


@dataclass
class ComparisonMatrix:
    """横向对比矩阵。

    rows:    metric_id 列表（按注册顺序）。
    columns: evaluable_name 列表。
    cells:   {metric_id: {evaluable_name: ComparisonCell}} 嵌套字典。
    """
    scope: str
    rows: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    cells: dict[str, dict[str, ComparisonCell]] = field(default_factory=dict)

    def get(self, metric_id: str, evaluable_name: str) -> ComparisonCell | None:
        """获取矩阵单元格。"""
        return self.cells.get(metric_id, {}).get(evaluable_name)

    def to_dict(self) -> dict:
        """序列化为可 JSON 持久化的字典结构。"""
        return {
            "scope": self.scope,
            "rows": self.rows,
            "columns": self.columns,
            "cells": {
                mid: {
                    ename: {
                        "value": cell.value,
                        "unit": cell.unit,
                    }
                    for ename, cell in col_map.items()
                }
                for mid, col_map in self.cells.items()
            },
        }


class ComparisonGroup:
    """构建多 evaluable 横向对比矩阵的工厂类。

    只在 stage 下有 ≥2 个 evaluable 时调用，由 BaseEvaluator.evaluate() 委托。
    """

    @staticmethod
    def build(
        outputs_by_evaluable: dict[str, list["StageOutput"]],
        samples: list["EvalSample"],
        registry: "MetricRegistry",
        scope: str,
    ) -> ComparisonMatrix:
        """构建横向对比矩阵。

        对每个 evaluable 的全量 outputs 运行所有 AggregateMetric，
        将结果填入矩阵对应单元格。SampleMetric 取均值作为代表值。

        Args:
            outputs_by_evaluable: evaluable_name → StageOutput 列表。
            samples:              对应的 EvalSample 列表。
            registry:             已过滤的指标注册表。
            scope:                stage 名称。

        Returns:
            ComparisonMatrix: 填充完毕的对比矩阵。
        """
        matrix = ComparisonMatrix(scope=scope)
        matrix.columns = list(outputs_by_evaluable.keys())

        sample_metrics = registry.sample_metrics_for(scope)
        aggregate_metrics = registry.aggregate_metrics_for(scope)
        all_metrics = sample_metrics + aggregate_metrics  # type: ignore

        # 收集所有 metric_id 作为行
        matrix.rows = [m.metric_id for m in all_metrics]

        for evaluable_name, outputs in outputs_by_evaluable.items():
            # AggregateMetric：直接全量计算
            for metric in aggregate_metrics:
                try:
                    result = metric.compute(outputs, samples)
                    matrix.cells.setdefault(result.metric_id, {})[evaluable_name] = ComparisonCell(
                        metric_id=result.metric_id,
                        evaluable_name=evaluable_name,
                        value=result.value,
                        unit=metric.unit,
                    )
                except Exception:
                    pass

            # SampleMetric：取成功样本的平均值作为矩阵代表值
            for metric in sample_metrics:
                values: list[float] = []
                for output, sample in zip(outputs, samples):
                    try:
                        result = metric.compute(output, sample)
                        if isinstance(result.value, (int, float)):
                            values.append(float(result.value))
                    except Exception:
                        pass
                avg_value = round(sum(values) / len(values), 4) if values else 0.0
                matrix.cells.setdefault(metric.metric_id, {})[evaluable_name] = ComparisonCell(
                    metric_id=metric.metric_id,
                    evaluable_name=evaluable_name,
                    value=avg_value,
                    unit=metric.unit,
                )

        return matrix
