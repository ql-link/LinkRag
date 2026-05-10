# -*- coding: utf-8 -*-
"""核心解耦协议定义层——全系统唯一的抽象协议定义处。"""

from .evaluable import Evaluable, StageInput, StageOutput
from .metric import MetricResult, SampleMetric, AggregateMetric
from .dataset import EvalSample, EvalDataset
from .judge import Judge, JudgeResult
from .store import ResultStore, EvalRun, EvalRunSummary
from .hook import EvalEvent, Hook

__all__ = [
    "Evaluable",
    "StageInput",
    "StageOutput",
    "MetricResult",
    "SampleMetric",
    "AggregateMetric",
    "EvalSample",
    "EvalDataset",
    "Judge",
    "JudgeResult",
    "ResultStore",
    "EvalRun",
    "EvalRunSummary",
    "EvalEvent",
    "Hook",
]
