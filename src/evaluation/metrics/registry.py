# -*- coding: utf-8 -*-
"""
MetricRegistry — 指标自动发现与 scope 过滤。

新增指标只需在 metrics/<scope>/ 下加文件并调用 register，
Evaluator 通过 scope 过滤获取对应指标，不改主流程。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.evaluation.contracts.metric import SampleMetric, AggregateMetric


class MetricRegistry:
    """全局指标注册表（进程级单例，类变量实现）。

    与 EvaluableRegistry 设计对称：YAML include/exclude glob 通过此表过滤。
    分 SampleMetric 和 AggregateMetric 两个分类存储，Runner 分两阶段调用。
    """

    _sample_metrics: dict[str, "SampleMetric"] = {}
    _aggregate_metrics: dict[str, "AggregateMetric"] = {}

    @classmethod
    def register_sample(cls, metric: "SampleMetric") -> None:
        """注册 SampleMetric。

        Args:
            metric: 实现了 SampleMetric 协议的实例。
        """
        cls._sample_metrics[metric.metric_id] = metric

    @classmethod
    def register_aggregate(cls, metric: "AggregateMetric") -> None:
        """注册 AggregateMetric。

        Args:
            metric: 实现了 AggregateMetric 协议的实例。
        """
        cls._aggregate_metrics[metric.metric_id] = metric

    @classmethod
    def sample_metrics_for(cls, scope: str) -> list["SampleMetric"]:
        """按 scope 获取所有已注册的 SampleMetric。

        Args:
            scope: 如 "parse" / "chunk" / "embed"。

        Returns:
            list[SampleMetric]: 属于该 scope 的所有逐样本指标。
        """
        return [m for m in cls._sample_metrics.values() if m.scope == scope]

    @classmethod
    def aggregate_metrics_for(cls, scope: str) -> list["AggregateMetric"]:
        """按 scope 获取所有已注册的 AggregateMetric。

        Args:
            scope: 如 "parse" / "chunk" / "embed"。

        Returns:
            list[AggregateMetric]: 属于该 scope 的所有聚合指标。
        """
        return [m for m in cls._aggregate_metrics.values() if m.scope == scope]

    @classmethod
    def filter_by_glob(
        cls,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> "MetricRegistry":
        """按 glob 模式过滤指标，返回新的临时注册表视图。

        用于 Pipeline YAML 中的 metrics.include / exclude 配置。
        glob 匹配规则：fnmatch 语义，如 "parse.*" 匹配所有 parse scope 指标。

        Args:
            include: 包含 glob 列表，None 表示全部包含。
            exclude: 排除 glob 列表，None 表示不排除。

        Returns:
            MetricRegistry: 新的注册表实例（不影响全局注册表）。
        """
        import fnmatch

        def _matches(metric_id: str, patterns: list[str]) -> bool:
            return any(fnmatch.fnmatch(metric_id, p) for p in patterns)

        filtered = MetricRegistry.__new__(MetricRegistry)
        filtered._sample_metrics = {}
        filtered._aggregate_metrics = {}

        for mid, m in cls._sample_metrics.items():
            if include and not _matches(mid, include):
                continue
            if exclude and _matches(mid, exclude):
                continue
            filtered._sample_metrics[mid] = m

        for mid, m in cls._aggregate_metrics.items():
            if include and not _matches(mid, include):
                continue
            if exclude and _matches(mid, exclude):
                continue
            filtered._aggregate_metrics[mid] = m

        return filtered

    @classmethod
    def all_metric_ids(cls) -> list[str]:
        """返回所有已注册指标的 metric_id 列表。

        Returns:
            list[str]: 全部指标 ID（SampleMetric + AggregateMetric）。
        """
        return list(cls._sample_metrics.keys()) + list(cls._aggregate_metrics.keys())

    @classmethod
    def clear(cls) -> None:
        """清空注册表（主要用于测试隔离）。"""
        cls._sample_metrics.clear()
        cls._aggregate_metrics.clear()
