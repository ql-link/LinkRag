# -*- coding: utf-8 -*-
"""JSON 格式评估报告渲染器。"""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from .base import BaseReporter

if TYPE_CHECKING:
    from src.evaluation.contracts.store import EvalRun


class JsonReporter(BaseReporter):
    """将评估结果渲染为 JSON 文件，支持 baseline delta 对比列。

    输出文件名：{run_id}.json，存放在 output_dir 目录下。
    """

    def render(self, run: "EvalRun", baseline: "EvalRun | None" = None) -> str:
        """渲染 JSON 报告。

        Args:
            run:      当前评估运行记录。
            baseline: 可选基准运行，有则附加 deltas 字段。

        Returns:
            str: 输出 JSON 文件的绝对路径。
        """
        run_id = run.summary.run_id
        output: dict = {
            "run_id": run_id,
            "dataset_name": run.summary.dataset_name,
            "status": run.summary.status,
            "created_at": run.summary.created_at,
            "sample_count": run.summary.sample_count,
            "success_count": run.summary.success_count,
            "metrics": run.metrics,
        }

        if baseline is not None:
            deltas = self._compute_deltas(run.metrics, baseline.metrics)
            output["baseline_run_id"] = baseline.summary.run_id
            output["deltas"] = deltas

        file_path = os.path.join(self.output_dir, f"{run_id}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        return os.path.abspath(file_path)
