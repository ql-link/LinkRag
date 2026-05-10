# -*- coding: utf-8 -*-
"""
Metric Protocol — 可插拔双层指标设计。

v2 相对 v1 的核心改进：区分 SampleMetric（逐样本）和 AggregateMetric（全数据集），
Runner 先逐 sample 调用 SampleMetric，收集完毕后统一调用 AggregateMetric。
新增指标只需加一个文件并实现对应 Protocol，不改主流程。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .evaluable import StageOutput
    from .dataset import EvalSample


@dataclass
class MetricResult:
    """单次指标计算结果。

    Attributes:
        metric_id: 三段式唯一标识，如 "parser.latency.p95"。
        value:     计算结果，支持单值 float、复合 dict（直方图）或 list。
        detail:    任意调试信息，如分位详情、失败样本列表等。
    """
    metric_id: str
    value: float | dict | list
    detail: dict = field(default_factory=dict)


class SampleMetric(Protocol):
    """逐样本指标协议：每个 sample 独立输出一个 MetricResult。

    适用场景：标题保留率、ROUGE-L、内容丢失率等需要逐条对齐 ground_truth 的指标。

    Attributes:
        metric_id:       三段式唯一标识，如 "parser.md_structure.heading_retention"。
        scope:           对应 stage，如 "parse" | "chunk" | "embed"。
        higher_is_better: True 表示指标值越高越好（如保留率），False 表示越低越好（如丢失率）。
        unit:            指标单位描述，如 "ratio" / "ms" / "count"。
    """
    metric_id: str
    scope: str
    higher_is_better: bool
    unit: str

    def compute(self, output: "StageOutput", sample: "EvalSample") -> MetricResult:
        """计算单个样本的指标值。

        Args:
            output: 被评估对象对此 sample 的输出。
            sample: 对应的数据集样本（含 ground_truth）。

        Returns:
            MetricResult: 本 sample 的指标计算结果。
        """
        ...


class AggregateMetric(Protocol):
    """全数据集聚合指标协议：接收所有 outputs 一次性计算。

    适用场景：P50/P95 耗时、长度分布直方图、跨标题切割率等统计类指标。

    Attributes:
        metric_id:       三段式唯一标识，如 "parser.latency.p95"。
        scope:           对应 stage。
        higher_is_better: 含义同 SampleMetric。
        unit:            指标单位描述。
    """
    metric_id: str
    scope: str
    higher_is_better: bool
    unit: str

    def compute(
        self,
        outputs: list["StageOutput"],
        samples: list["EvalSample"],
    ) -> MetricResult:
        """聚合计算全数据集级别的指标值。

        Args:
            outputs: 本 stage 所有样本的执行结果列表（顺序与 samples 对应）。
            samples: 对应的数据集样本列表。

        Returns:
            MetricResult: 聚合后的指标计算结果。
        """
        ...
