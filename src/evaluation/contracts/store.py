# -*- coding: utf-8 -*-
"""
ResultStore Protocol — 评估结果持久化接口。

默认实现 = 文件系统（JSON Lines），可扩展为 MySQL。
存储层与 Runner 完全解耦：Reporter 从 Store 读取渲染，支持后验生成报告。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol, Any


@dataclass
class EvalRunSummary:
    """评估运行摘要（用于列表查询，不含完整 metrics）。

    Attributes:
        run_id:       运行唯一标识（UUID）。
        dataset_name: 使用的数据集名称。
        pipeline_config: 使用的 pipeline yaml 路径或内容摘要。
        created_at:   运行创建时间戳（Unix 秒）。
        status:       运行状态：running / done / failed。
        sample_count: 总样本数。
        success_count: 成功样本数。
    """
    run_id: str
    dataset_name: str
    pipeline_config: str
    created_at: float = field(default_factory=time.time)
    status: str = "running"
    sample_count: int = 0
    success_count: int = 0


@dataclass
class EvalRun:
    """完整评估运行记录，含 metrics 结果。

    Attributes:
        summary:      运行摘要信息。
        metrics:      所有指标结果列表（序列化后的 MetricResult 字典）。
        sample_outputs: 各样本各 evaluable 的 StageOutput（序列化）。
        extra:        扩展字段，存储 pipeline 配置快照等。
    """
    summary: EvalRunSummary
    metrics: list[dict] = field(default_factory=list)
    sample_outputs: list[dict] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


class ResultStore(Protocol):
    """结果持久化协议。

    Runner 通过此协议保存评估运行结果，Reporter 通过此协议读取用于渲染。
    实现者可选择文件系统、MySQL 等后端，不影响 Runner / Reporter 逻辑。
    """

    async def save_run(self, run: EvalRun) -> str:
        """持久化完整评估运行记录。

        Args:
            run: 完整运行记录（含 metrics）。

        Returns:
            str: 持久化后的 run_id。
        """
        ...

    async def load_run(self, run_id: str) -> EvalRun | None:
        """按 run_id 加载运行记录。

        Args:
            run_id: 运行唯一标识。

        Returns:
            EvalRun | None: 运行记录，不存在时返回 None。
        """
        ...

    async def list_runs(self, **filters) -> list[EvalRunSummary]:
        """列出历史运行记录（可按 dataset_name / status 过滤）。

        Args:
            **filters: 过滤条件，支持 dataset_name=str, status=str。

        Returns:
            list[EvalRunSummary]: 运行摘要列表，按 created_at 倒序。
        """
        ...

    async def save_metrics(self, run_id: str, results: list[dict]) -> None:
        """追加保存指标结果（支持分阶段写入）。

        Args:
            run_id:  运行唯一标识。
            results: MetricResult 序列化后的字典列表。
        """
        ...

    async def load_baseline(self, dataset_name: str) -> EvalRun | None:
        """加载同数据集最近一次成功运行，用于趋势对比。

        Args:
            dataset_name: 数据集名称。

        Returns:
            EvalRun | None: 基准运行记录，不存在时返回 None。
        """
        ...
