# -*- coding: utf-8 -*-
"""ParserEvaluator — parse stage 的维度评估器。"""
from .base import BaseEvaluator


class ParserEvaluator(BaseEvaluator):
    """parse stage 评估器，scope = "parse"。

    继承 BaseEvaluator 两阶段逻辑，只需声明 scope。
    所有 parse scope 的 SampleMetric / AggregateMetric 通过 MetricRegistry 注入，
    不在此处硬编码，保证开闭原则（新增指标不改此类）。
    """
    scope = "parse"
