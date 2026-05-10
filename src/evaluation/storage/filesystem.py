# -*- coding: utf-8 -*-
"""
FilesystemResultStore — 文件系统 ResultStore 实现（JSON Lines）。

默认存储后端，零外部依赖。每个 run 存储为独立的 JSON 文件，
按 run_id 命名，便于直接查看。支持 baseline 自动查找（同 dataset 最近成功 run）。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from src.evaluation.contracts.store import EvalRun, EvalRunSummary


class FilesystemResultStore:
    """基于文件系统的 ResultStore 实现。

    目录结构：
        store_dir/
          runs/
            {run_id}.json    完整 EvalRun 序列化文件
          index.jsonl          运行索引（每行一个 EvalRunSummary）

    Attributes:
        store_dir: 存储根目录，自动创建。
    """

    def __init__(self, store_dir: str = "./.eval_store") -> None:
        self.store_dir = store_dir
        self._runs_dir = os.path.join(store_dir, "runs")
        self._index_path = os.path.join(store_dir, "index.jsonl")
        os.makedirs(self._runs_dir, exist_ok=True)

    async def save_run(self, run: EvalRun) -> str:
        """持久化完整评估运行记录为 JSON 文件。

        Args:
            run: 完整运行记录。

        Returns:
            str: run_id。
        """
        run_id = run.summary.run_id
        run_data = {
            "summary": {
                "run_id": run_id,
                "dataset_name": run.summary.dataset_name,
                "pipeline_config": run.summary.pipeline_config,
                "created_at": run.summary.created_at,
                "status": run.summary.status,
                "sample_count": run.summary.sample_count,
                "success_count": run.summary.success_count,
            },
            "metrics": run.metrics,
            "sample_outputs": run.sample_outputs,
            "extra": run.extra,
        }

        file_path = os.path.join(self._runs_dir, f"{run_id}.json")
        await asyncio.to_thread(
            self._write_json, file_path, run_data,
        )

        # 更新索引
        index_entry = {
            "run_id": run_id,
            "dataset_name": run.summary.dataset_name,
            "pipeline_config": run.summary.pipeline_config,
            "created_at": run.summary.created_at,
            "status": run.summary.status,
            "sample_count": run.summary.sample_count,
            "success_count": run.summary.success_count,
        }
        await asyncio.to_thread(self._append_index, index_entry)

        return run_id

    async def load_run(self, run_id: str) -> EvalRun | None:
        """按 run_id 加载运行记录。

        Args:
            run_id: 运行唯一标识。

        Returns:
            EvalRun | None: 不存在时返回 None。
        """
        file_path = os.path.join(self._runs_dir, f"{run_id}.json")
        if not os.path.exists(file_path):
            return None

        raw = await asyncio.to_thread(self._read_json, file_path)
        return self._deserialize(raw)

    async def list_runs(self, **filters) -> list[EvalRunSummary]:
        """列出历史运行记录（按 created_at 倒序）。

        Args:
            **filters: 支持 dataset_name=str, status=str。

        Returns:
            list[EvalRunSummary]: 运行摘要列表。
        """
        summaries = await asyncio.to_thread(self._read_index)

        if "dataset_name" in filters:
            summaries = [s for s in summaries if s.dataset_name == filters["dataset_name"]]
        if "status" in filters:
            summaries = [s for s in summaries if s.status == filters["status"]]

        return sorted(summaries, key=lambda s: s.created_at, reverse=True)

    async def save_metrics(self, run_id: str, results: list[dict]) -> None:
        """追加保存指标结果（追加写入已有 run JSON）。

        Args:
            run_id:  运行唯一标识。
            results: MetricResult 序列化后的字典列表。
        """
        existing = await self.load_run(run_id)
        if existing is None:
            return
        existing.metrics.extend(results)
        await self.save_run(existing)

    async def load_baseline(self, dataset_name: str) -> EvalRun | None:
        """加载同数据集最近一次成功运行，用于趋势对比。

        Args:
            dataset_name: 数据集名称。

        Returns:
            EvalRun | None: 基准运行记录，不存在时返回 None。
        """
        candidates = await self.list_runs(dataset_name=dataset_name, status="done")
        if not candidates:
            return None

        # 返回最近一次（list_runs 已按 created_at 倒序）
        return await self.load_run(candidates[0].run_id)

    # ── 私有同步 IO 方法（通过 asyncio.to_thread 调用）─────────────────────────

    @staticmethod
    def _write_json(file_path: str, data: Any) -> None:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _read_json(file_path: str) -> Any:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _append_index(self, entry: dict) -> None:
        with open(self._index_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _read_index(self) -> list[EvalRunSummary]:
        if not os.path.exists(self._index_path):
            return []
        summaries: list[EvalRunSummary] = []
        with open(self._index_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                    summaries.append(EvalRunSummary(
                        run_id=raw["run_id"],
                        dataset_name=raw["dataset_name"],
                        pipeline_config=raw.get("pipeline_config", ""),
                        created_at=raw.get("created_at", 0.0),
                        status=raw.get("status", "done"),
                        sample_count=raw.get("sample_count", 0),
                        success_count=raw.get("success_count", 0),
                    ))
                except Exception:
                    continue
        return summaries

    @staticmethod
    def _deserialize(raw: dict) -> EvalRun:
        s = raw["summary"]
        summary = EvalRunSummary(
            run_id=s["run_id"],
            dataset_name=s["dataset_name"],
            pipeline_config=s.get("pipeline_config", ""),
            created_at=s.get("created_at", 0.0),
            status=s.get("status", "done"),
            sample_count=s.get("sample_count", 0),
            success_count=s.get("success_count", 0),
        )
        return EvalRun(
            summary=summary,
            metrics=raw.get("metrics", []),
            sample_outputs=raw.get("sample_outputs", []),
            extra=raw.get("extra", {}),
        )
