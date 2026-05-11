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
        if self.output_dir is None:
            raise ValueError("JsonReporter.render 需要 output_dir；远端上传请使用 render_bytes")
        run_id = run.summary.run_id
        output = self._build_report(run, baseline)
        file_path = os.path.join(self.output_dir, f"{run_id}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        return os.path.abspath(file_path)

    def render_bytes(self, run: "EvalRun", baseline: "EvalRun | None" = None) -> tuple[bytes, str, str]:
        content = json.dumps(self._build_report(run, baseline), ensure_ascii=False, indent=2)
        return content.encode("utf-8"), "json", "application/json"

    def _build_report(self, run: "EvalRun", baseline: "EvalRun | None" = None) -> dict:
        output: dict = {
            "run_id": run.summary.run_id,
            "dataset_name": run.summary.dataset_name,
            "status": run.summary.status,
            "created_at": run.summary.created_at,
            "sample_count": run.summary.sample_count,
            "success_count": run.summary.success_count,
            "metrics": run.metrics,
        }
        if baseline is not None:
            output["baseline_run_id"] = baseline.summary.run_id
            output["deltas"] = self._compute_deltas(run.metrics, baseline.metrics)
        return output
