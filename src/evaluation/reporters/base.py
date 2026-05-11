# -*- coding: utf-8 -*-
"""
BaseReporter — 报告渲染基类。

Reporter 接受可选 baseline: EvalRun 参数，输出 delta 对比列，支持趋势分析。
子类实现 render() 具体格式（JSON / Markdown / HTML）。
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.evaluation.contracts.store import EvalRun


class BaseReporter(ABC):
    """报告渲染基类。

    Attributes:
        output_dir: 报告输出目录，自动创建。
    """

    def __init__(self, output_dir: str | None = "./docs/evaluation_reports") -> None:
        self.output_dir = output_dir
        if output_dir is not None:
            os.makedirs(output_dir, exist_ok=True)

    @abstractmethod
    def render(self, run: "EvalRun", baseline: "EvalRun | None" = None) -> str:
        """渲染报告并写入文件。

        Args:
            run:      当前评估运行记录。
            baseline: 可选基准运行记录，用于趋势对比输出 delta 列。

        Returns:
            str: 输出文件的绝对路径。
        """
        ...

    @abstractmethod
    def render_bytes(self, run: "EvalRun", baseline: "EvalRun | None" = None) -> tuple[bytes, str, str]:
        """渲染报告为 bytes，用于远端 ResultStore 上传。

        Returns:
            tuple[bytes, str, str]: content, format_name, content_type。
        """
        ...

    def _compute_deltas(
        self,
        current_metrics: list[dict],
        baseline_metrics: list[dict],
    ) -> dict[str, float | None]:
        """计算当前与基准间各指标的 delta（当前值 - 基准值）。O(n)。

        仅对 value 为 float 的简单指标计算 delta，复合指标（dict/list）跳过。

        Args:
            current_metrics:  当前运行的 metrics 列表（序列化字典）。
            baseline_metrics: 基准运行的 metrics 列表。

        Returns:
            dict[str, float | None]: {metric_id: delta}，delta 可为 None（无法计算）。
        """
        baseline_map = {m["metric_id"]: m["value"] for m in baseline_metrics}
        deltas: dict[str, float | None] = {}

        for m in current_metrics:
            mid = m["metric_id"]
            cur_val = m["value"]
            base_val = baseline_map.get(mid)

            if isinstance(cur_val, (int, float)) and isinstance(base_val, (int, float)):
                deltas[mid] = round(float(cur_val) - float(base_val), 4)
            else:
                deltas[mid] = None

        return deltas
