# -*- coding: utf-8 -*-
"""Parser quality score and Top 3 ranking metrics."""
from __future__ import annotations

from src.evaluation.contracts.dataset import EvalSample
from src.evaluation.contracts.evaluable import StageOutput
from src.evaluation.contracts.metric import MetricResult

from .heading_quality import HeadingCoverageMetric, HeadingLevelAccuracyMetric
from .image_quality import ImageQualityMetric
from .table_quality import TableQualityMetric
from .text_completeness import TextCompletenessMetric


class ParserSampleQualityMetric:
    metric_id = "parser.quality.sample_score"
    scope = "parse"
    higher_is_better = True
    unit = "score"

    def compute(self, output: StageOutput, sample: EvalSample) -> MetricResult:
        detail = compute_sample_quality(output, sample)
        return MetricResult(
            metric_id=self.metric_id,
            value=detail["sample_quality_score"],
            detail=detail,
        )


class ParserTotalScoreMetric:
    metric_id = "parser.quality.total_score"
    scope = "parse"
    higher_is_better = True
    unit = "score"

    def compute(self, outputs: list[StageOutput], samples: list[EvalSample]) -> MetricResult:
        if not outputs:
            return MetricResult(self.metric_id, 0.0, {"sample_count": 0})
        details = [
            compute_sample_quality(output, sample)
            for output, sample in zip(outputs, samples)
        ]
        avg_quality = sum(item["sample_quality_score"] for item in details) / len(details)
        success_rate = sum(1 for output in outputs if output.success) / len(outputs)
        avg_performance = sum(item["performance_score"] for item in details) / len(details)
        total_score = round(0.7 * avg_quality + 0.2 * (100 * success_rate) + 0.1 * avg_performance, 2)
        return MetricResult(
            metric_id=self.metric_id,
            value=total_score,
            detail={
                "sample_count": len(details),
                "avg_sample_quality_score": round(avg_quality, 2),
                "success_rate_score": round(100 * success_rate, 2),
                "aggregate_performance_score": round(avg_performance, 2),
            },
        )


class TopSampleRankingMetric:
    metric_id = "parser.quality.top_samples"
    scope = "parse"
    higher_is_better = True
    unit = "rank"

    def compute(self, outputs: list[StageOutput], samples: list[EvalSample]) -> MetricResult:
        records = [
            _ranking_record(output, sample)
            for output, sample in zip(outputs, samples)
        ]
        best = sorted(
            records,
            key=lambda item: (
                item["sample_quality_score"],
                item["table_score"],
                item["heading_score"],
                -item["elapsed_ms"],
            ),
            reverse=True,
        )[:3]
        failed = [item for item in records if not item["success"]]
        failed_sorted = sorted(
            failed,
            key=lambda item: (
                item["error_type"] or "",
                -item["elapsed_ms"],
            ),
        )
        remaining = [
            item for item in sorted(records, key=lambda item: item["sample_quality_score"])
            if item not in failed_sorted
        ]
        worst = (failed_sorted + remaining)[:3]
        return MetricResult(
            metric_id=self.metric_id,
            value={"best_top3": best, "worst_top3": worst},
            detail={"sample_count": len(records)},
        )


def compute_sample_quality(output: StageOutput, sample: EvalSample) -> dict:
    if not output.success or not output.payload:
        return {
            "sample_id": sample.sample_id,
            "success": False,
            "error_type": output.error_type,
            "elapsed_ms": round(output.elapsed_ms, 2),
            "text_score": 0.0,
            "heading_score": 0.0,
            "image_score": 0.0,
            "table_score": 0.0,
            "performance_score": 0.0,
            "sample_quality_score": 0.0,
        }
    text_result = TextCompletenessMetric().compute(output, sample)
    heading_coverage = HeadingCoverageMetric().compute(output, sample)
    heading_level = HeadingLevelAccuracyMetric().compute(output, sample)
    image_result = ImageQualityMetric().compute(output, sample)
    table_result = TableQualityMetric().compute(output, sample)
    text_score = float(text_result.value) * 100
    heading_score = 100 * (0.4 * float(heading_coverage.value) + 0.6 * float(heading_level.value))
    image_score = float(image_result.value) * 100
    table_score = float(table_result.value) * 100
    performance_score = _performance_score(output.elapsed_ms)
    sample_quality_score = round(
        0.30 * table_score
        + 0.25 * heading_score
        + 0.20 * image_score
        + 0.15 * text_score
        + 0.10 * performance_score,
        2,
    )
    return {
        "sample_id": sample.sample_id,
        "file_type": sample.file_type,
        "success": True,
        "error_type": None,
        "elapsed_ms": round(output.elapsed_ms, 2),
        "text_score": round(text_score, 2),
        "heading_score": round(heading_score, 2),
        "image_score": round(image_score, 2),
        "table_score": round(table_score, 2),
        "performance_score": round(performance_score, 2),
        "sample_quality_score": sample_quality_score,
        "text_detail": text_result.detail,
        "heading_detail": {
            "heading_coverage": heading_coverage.value,
            "heading_level_accuracy": heading_level.value,
        },
        "image_detail": image_result.detail,
        "table_detail": table_result.detail,
    }


def _performance_score(elapsed_ms: float) -> float:
    if elapsed_ms <= 0:
        return 100.0
    reference_elapsed_ms = 10000.0
    return min(100.0, round(100 * reference_elapsed_ms / elapsed_ms, 2))


def _ranking_record(output: StageOutput, sample: EvalSample) -> dict:
    detail = compute_sample_quality(output, sample)
    return {
        "sample_id": sample.sample_id,
        "file_type": sample.file_type,
        "success": detail["success"],
        "sample_quality_score": detail["sample_quality_score"],
        "table_score": detail["table_score"],
        "heading_score": detail["heading_score"],
        "elapsed_ms": detail["elapsed_ms"],
        "error_type": detail["error_type"],
    }
