# -*- coding: utf-8 -*-
"""Archive best/worst parser evaluation samples to MinIO."""
from __future__ import annotations

import json
from typing import Any

from src.evaluation.contracts.dataset import EvalSample
from src.evaluation.contracts.evaluable import StageOutput
from src.evaluation.contracts.store import EvalRun


class Top3Archiver:
    """Persist small review packs for best and worst ranked samples."""

    async def archive(
        self,
        run: EvalRun,
        samples: list[EvalSample],
        outputs_by_evaluable: dict[str, list[StageOutput]],
        store,
    ) -> dict:
        result = {"best_top3": [], "worst_top3": [], "errors": []}
        sample_map = {sample.sample_id: sample for sample in samples}
        outputs_map = {
            (sample.sample_id, evaluable_name): output
            for evaluable_name, outputs in outputs_by_evaluable.items()
            for sample, output in zip(samples, outputs)
        }
        for metric in _top_sample_metrics(run):
            evaluable_name = metric.get("detail", {}).get("evaluable_name", "")
            for group in ("best_top3", "worst_top3"):
                for rank, item in enumerate(metric.get("value", {}).get(group, []), start=1):
                    sample_id = item.get("sample_id")
                    sample = sample_map.get(sample_id)
                    output = outputs_map.get((sample_id, evaluable_name))
                    if sample is None or output is None:
                        continue
                    try:
                        archived = await self._archive_one(
                            run=run,
                            store=store,
                            group=group,
                            rank=rank,
                            item=item,
                            sample=sample,
                            output=output,
                            evaluable_name=evaluable_name,
                        )
                        result[group].append(archived)
                    except Exception as exc:
                        result["errors"].append({
                            "group": group,
                            "sample_id": sample_id,
                            "evaluable_name": evaluable_name,
                            "error": str(exc),
                        })
        return result

    async def _archive_one(
        self,
        run: EvalRun,
        store,
        group: str,
        rank: int,
        item: dict,
        sample: EvalSample,
        output: StageOutput,
        evaluable_name: str,
    ) -> dict:
        base = f"{group}/{rank}_{sample.sample_id}_{evaluable_name}"
        gt_md = sample.ground_truth.get("markdown", "")
        parsed_md = output.payload or ""
        metrics_payload = json.dumps(item, ensure_ascii=False, indent=2).encode("utf-8")
        keys = {
            "ground_truth_key": await store.save_artifact(
                run.summary.dataset_name,
                run.summary.run_id,
                f"{base}/ground_truth.md",
                str(gt_md).encode("utf-8"),
                "text/markdown; charset=utf-8",
            ),
            "parsed_key": await store.save_artifact(
                run.summary.dataset_name,
                run.summary.run_id,
                f"{base}/parsed.md",
                str(parsed_md).encode("utf-8"),
                "text/markdown; charset=utf-8",
            ),
            "metrics_key": await store.save_artifact(
                run.summary.dataset_name,
                run.summary.run_id,
                f"{base}/metrics.json",
                metrics_payload,
                "application/json",
            ),
            "diff_summary_key": await store.save_artifact(
                run.summary.dataset_name,
                run.summary.run_id,
                f"{base}/diff_summary.md",
                self._build_diff_summary(gt_md, parsed_md, item).encode("utf-8"),
                "text/markdown; charset=utf-8",
            ),
        }
        source_ref = sample.remote_file.key if sample.remote_file else sample.file_path
        return {
            "rank": rank,
            "sample_id": sample.sample_id,
            "evaluable_name": evaluable_name,
            "source_ref": source_ref,
            **item,
            **keys,
        }

    def _build_diff_summary(self, gt_md: str, parsed_md: str, metrics: dict[str, Any]) -> str:
        return "\n".join([
            "# Top 3 解析复盘摘要",
            "",
            f"- sample_id: `{metrics.get('sample_id', '')}`",
            f"- sample_quality_score: `{metrics.get('sample_quality_score', '')}`",
            f"- success: `{metrics.get('success', '')}`",
            f"- elapsed_ms: `{metrics.get('elapsed_ms', '')}`",
            f"- ground_truth_chars: `{len(str(gt_md))}`",
            f"- parsed_chars: `{len(str(parsed_md))}`",
        ])


def _top_sample_metrics(run: EvalRun) -> list[dict]:
    return [
        metric for metric in run.metrics
        if metric.get("metric_id") == "parser.quality.top_samples"
    ]
