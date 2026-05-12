# -*- coding: utf-8 -*-
"""Parser heading quality metrics."""
from __future__ import annotations

from src.evaluation.contracts.dataset import EvalSample
from src.evaluation.contracts.evaluable import StageOutput
from src.evaluation.contracts.metric import MetricResult

from .structure_extractors import HeadingNode, extract_headings


class HeadingCoverageMetric:
    metric_id = "parser.heading.coverage"
    scope = "parse"
    higher_is_better = True
    unit = "ratio"

    def compute(self, output: StageOutput, sample: EvalSample) -> MetricResult:
        gt_headings = extract_headings(sample.ground_truth.get("markdown", ""))
        if not gt_headings:
            return MetricResult(self.metric_id, 1.0, {"sample_id": sample.sample_id, "gt_headings": 0})
        if not output.success or not output.payload:
            return MetricResult(self.metric_id, 0.0, {"sample_id": sample.sample_id, "skipped": True})
        out_headings = extract_headings(output.payload)
        pairs = _align_headings(gt_headings, out_headings)
        return MetricResult(
            metric_id=self.metric_id,
            value=round(len(pairs) / len(gt_headings), 4),
            detail={
                "sample_id": sample.sample_id,
                "gt_heading_count": len(gt_headings),
                "out_heading_count": len(out_headings),
                "matched_heading_count": len(pairs),
            },
        )


class HeadingLevelAccuracyMetric:
    metric_id = "parser.heading.level_accuracy"
    scope = "parse"
    higher_is_better = True
    unit = "ratio"

    def compute(self, output: StageOutput, sample: EvalSample) -> MetricResult:
        gt_headings = extract_headings(sample.ground_truth.get("markdown", ""))
        if not gt_headings:
            return MetricResult(self.metric_id, 1.0, {"sample_id": sample.sample_id, "gt_headings": 0})
        if not output.success or not output.payload:
            return MetricResult(self.metric_id, 0.0, {"sample_id": sample.sample_id, "skipped": True})
        out_headings = extract_headings(output.payload)
        pairs = _align_headings(gt_headings, out_headings)
        if not pairs:
            return MetricResult(self.metric_id, 0.0, {"sample_id": sample.sample_id, "matched": 0})
        offsets = [actual.level - expected.level for expected, actual in pairs]
        if len(set(offsets)) == 1:
            return MetricResult(
                metric_id=self.metric_id,
                value=1.0,
                detail={
                    "sample_id": sample.sample_id,
                    "matched": len(pairs),
                    "global_level_offset": offsets[0],
                },
            )
        correct = 0
        for expected, actual in pairs:
            parent_pair = _find_pair_by_expected_index(pairs, expected.parent_index)
            if parent_pair is None:
                correct += 1
                continue
            expected_parent, actual_parent = parent_pair
            expected_delta = expected.level - expected_parent.level
            actual_delta = actual.level - actual_parent.level
            if expected_delta == actual_delta:
                correct += 1
        return MetricResult(
            metric_id=self.metric_id,
            value=round(correct / len(pairs), 4),
            detail={
                "sample_id": sample.sample_id,
                "matched": len(pairs),
                "correct_relative_level_count": correct,
                "offsets": offsets,
            },
        )


def _align_headings(
    expected: list[HeadingNode],
    actual: list[HeadingNode],
) -> list[tuple[HeadingNode, HeadingNode]]:
    pairs: list[tuple[HeadingNode, HeadingNode]] = []
    used: set[int] = set()
    cursor = 0
    for item in expected:
        for idx in range(cursor, len(actual)):
            if idx in used:
                continue
            if actual[idx].text == item.text:
                pairs.append((item, actual[idx]))
                used.add(idx)
                cursor = idx + 1
                break
    return pairs


def _find_pair_by_expected_index(
    pairs: list[tuple[HeadingNode, HeadingNode]],
    expected_index: int | None,
) -> tuple[HeadingNode, HeadingNode] | None:
    if expected_index is None:
        return None
    for pair in pairs:
        if pair[0].index == expected_index:
            return pair
    return None
