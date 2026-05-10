# -*- coding: utf-8 -*-
"""ChunkerEvaluator — chunk stage 的维度评估器。"""
from .base import BaseEvaluator


class ChunkerEvaluator(BaseEvaluator):
    """chunk stage 评估器，scope = "chunk"。

    继承 BaseEvaluator 两阶段逻辑，只需声明 scope。
    所有 chunk scope 的 SampleMetric / AggregateMetric 通过 MetricRegistry 注入，
    新增指标不改此类。
    """
    scope = "chunk"
