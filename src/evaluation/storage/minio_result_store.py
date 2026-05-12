# -*- coding: utf-8 -*-
"""MinIO ResultStore implementation for evaluation runs."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from src.evaluation.contracts.store import EvalRun, EvalRunSummary


class MinioResultStore:
    """Persist evaluation runs, reports, and baselines to MinIO."""

    def __init__(
        self,
        object_storage,
        bucket: str = "test_set",
        run_prefix: str = "runs",
        report_prefix: str = "reports",
        baseline_prefix: str = "baselines",
    ) -> None:
        self._object_storage = object_storage
        self.bucket = bucket
        self.run_prefix = run_prefix.strip("/")
        self.report_prefix = report_prefix.strip("/")
        self.baseline_prefix = baseline_prefix.strip("/")

    async def save_run(self, run: EvalRun) -> str:
        run_id = run.summary.run_id
        dataset_name = run.summary.dataset_name
        payload = self._serialize(run)
        content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

        await asyncio.to_thread(
            self._object_storage.upload_bytes,
            self.bucket,
            self._run_key(dataset_name, run_id),
            content,
            "application/json",
        )
        # A by-id copy keeps the existing ResultStore.load_run(run_id) API usable.
        await asyncio.to_thread(
            self._object_storage.upload_bytes,
            self.bucket,
            self._run_by_id_key(run_id),
            content,
            "application/json",
        )
        await self._upsert_index(self._dataset_index_key(dataset_name), run.summary)
        await self._upsert_index(self._global_index_key(), run.summary)
        return run_id

    async def load_run(self, run_id: str) -> EvalRun | None:
        try:
            content = await asyncio.to_thread(
                self._object_storage.download_bytes,
                self.bucket,
                self._run_by_id_key(run_id),
            )
        except FileNotFoundError:
            return None
        return self._deserialize(json.loads(content.decode("utf-8")))

    async def list_runs(self, **filters) -> list[EvalRunSummary]:
        dataset_name = filters.get("dataset_name")
        key = self._dataset_index_key(dataset_name) if dataset_name else self._global_index_key()
        summaries = await self._read_index(key)
        if "status" in filters:
            summaries = [s for s in summaries if s.status == filters["status"]]
        return sorted(summaries, key=lambda s: s.created_at, reverse=True)

    async def save_metrics(self, run_id: str, results: list[dict]) -> None:
        existing = await self.load_run(run_id)
        if existing is None:
            return
        existing.metrics.extend(results)
        await self.save_run(existing)

    async def load_baseline(self, dataset_name: str) -> EvalRun | None:
        pointer_key = self._baseline_latest_key(dataset_name)
        try:
            content = await asyncio.to_thread(
                self._object_storage.download_bytes,
                self.bucket,
                pointer_key,
            )
        except FileNotFoundError:
            return None
        try:
            pointer = json.loads(content.decode("utf-8"))
            run_id = pointer["run_id"]
        except Exception:
            return None
        return await self.load_run(run_id)

    async def save_report(
        self,
        dataset_name: str,
        run_id: str,
        format_name: str,
        content: bytes,
        content_type: str,
    ) -> str:
        suffix = "md" if format_name == "markdown" else format_name
        key = self._join_key(self.report_prefix, dataset_name, run_id, f"report.{suffix}")
        await asyncio.to_thread(
            self._object_storage.upload_bytes,
            self.bucket,
            key,
            content,
            content_type,
        )
        return key

    async def save_artifact(
        self,
        dataset_name: str,
        run_id: str,
        relative_path: str,
        content: bytes,
        content_type: str,
    ) -> str:
        key = self._join_key(
            self.report_prefix,
            dataset_name,
            run_id,
            "artifacts",
            self._safe_relative_path(relative_path),
        )
        await asyncio.to_thread(
            self._object_storage.upload_bytes,
            self.bucket,
            key,
            content,
            content_type,
        )
        return key

    async def save_parsed_result(
        self,
        dataset_name: str,
        run_id: str,
        sample_id: str,
        evaluable_name: str,
        markdown: str,
        metadata: dict,
    ) -> dict:
        safe_sample_id = self._safe_key_part(sample_id)
        safe_evaluable = self._safe_key_part(evaluable_name)
        base_key = self._join_key(
            self.report_prefix,
            dataset_name,
            run_id,
            "parsed",
            safe_sample_id,
            safe_evaluable,
        )
        markdown_key = self._join_key(base_key, "parsed.md")
        metadata_key = self._join_key(base_key, "metadata.json")
        await asyncio.to_thread(
            self._object_storage.upload_bytes,
            self.bucket,
            markdown_key,
            markdown.encode("utf-8"),
            "text/markdown; charset=utf-8",
        )
        await asyncio.to_thread(
            self._object_storage.upload_bytes,
            self.bucket,
            metadata_key,
            json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json",
        )
        return {
            "parsed_markdown_key": markdown_key,
            "metadata_key": metadata_key,
        }

    async def promote_baseline(self, dataset_name: str, run_id: str) -> None:
        payload = {
            "dataset_name": dataset_name,
            "run_id": run_id,
            "promoted_at": time.time(),
        }
        content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        await asyncio.to_thread(
            self._object_storage.upload_bytes,
            self.bucket,
            self._baseline_latest_key(dataset_name),
            content,
            "application/json",
        )
        await asyncio.to_thread(
            self._object_storage.upload_bytes,
            self.bucket,
            self._join_key(self.baseline_prefix, dataset_name, f"{run_id}.json"),
            content,
            "application/json",
        )

    async def _upsert_index(self, key: str, summary: EvalRunSummary) -> None:
        summaries = await self._read_index(key)
        summaries = [item for item in summaries if item.run_id != summary.run_id]
        summaries.append(summary)
        lines = [
            json.dumps(self._summary_to_dict(item), ensure_ascii=False)
            for item in sorted(summaries, key=lambda s: s.created_at)
        ]
        content = ("\n".join(lines) + "\n").encode("utf-8")
        await asyncio.to_thread(
            self._object_storage.upload_bytes,
            self.bucket,
            key,
            content,
            "application/x-ndjson",
        )

    async def _read_index(self, key: str) -> list[EvalRunSummary]:
        try:
            content = await asyncio.to_thread(
                self._object_storage.download_bytes,
                self.bucket,
                key,
            )
        except FileNotFoundError:
            return []
        summaries: list[EvalRunSummary] = []
        for line in content.decode("utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            summaries.append(self._summary_from_dict(raw))
        return summaries

    def _run_key(self, dataset_name: str, run_id: str) -> str:
        return self._join_key(self.run_prefix, dataset_name, run_id, "run.json")

    def _run_by_id_key(self, run_id: str) -> str:
        return self._join_key(self.run_prefix, "by_id", f"{run_id}.json")

    def _dataset_index_key(self, dataset_name: str) -> str:
        return self._join_key(self.run_prefix, dataset_name, "index.jsonl")

    def _global_index_key(self) -> str:
        return self._join_key(self.run_prefix, "index.jsonl")

    def _baseline_latest_key(self, dataset_name: str) -> str:
        return self._join_key(self.baseline_prefix, dataset_name, "latest.json")

    @staticmethod
    def _join_key(*parts: str) -> str:
        return "/".join(str(part).strip("/") for part in parts if str(part).strip("/"))

    @staticmethod
    def _safe_key_part(value: str) -> str:
        return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value))

    @classmethod
    def _safe_relative_path(cls, value: str) -> str:
        parts = [
            cls._safe_key_part(part)
            for part in str(value).replace("\\", "/").split("/")
            if part and part not in {".", ".."}
        ]
        return "/".join(parts)

    @staticmethod
    def _serialize(run: EvalRun) -> dict[str, Any]:
        return {
            "summary": MinioResultStore._summary_to_dict(run.summary),
            "metrics": run.metrics,
            "sample_outputs": run.sample_outputs,
            "extra": run.extra,
        }

    @staticmethod
    def _deserialize(raw: dict[str, Any]) -> EvalRun:
        return EvalRun(
            summary=MinioResultStore._summary_from_dict(raw["summary"]),
            metrics=raw.get("metrics", []),
            sample_outputs=raw.get("sample_outputs", []),
            extra=raw.get("extra", {}),
        )

    @staticmethod
    def _summary_to_dict(summary: EvalRunSummary) -> dict[str, Any]:
        return {
            "run_id": summary.run_id,
            "dataset_name": summary.dataset_name,
            "pipeline_config": summary.pipeline_config,
            "created_at": summary.created_at,
            "status": summary.status,
            "sample_count": summary.sample_count,
            "success_count": summary.success_count,
        }

    @staticmethod
    def _summary_from_dict(raw: dict[str, Any]) -> EvalRunSummary:
        return EvalRunSummary(
            run_id=raw["run_id"],
            dataset_name=raw["dataset_name"],
            pipeline_config=raw.get("pipeline_config", ""),
            created_at=raw.get("created_at", 0.0),
            status=raw.get("status", "done"),
            sample_count=raw.get("sample_count", 0),
            success_count=raw.get("success_count", 0),
        )
