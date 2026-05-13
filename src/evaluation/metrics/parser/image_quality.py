# -*- coding: utf-8 -*-
"""Parser image quality metrics."""
from __future__ import annotations

from src.evaluation.contracts.dataset import EvalSample
from src.evaluation.contracts.evaluable import StageOutput
from src.evaluation.contracts.metric import MetricResult

from .structure_extractors import ImageAnchor, extract_images


class ImageQualityMetric:
    metric_id = "parser.image.quality"
    scope = "parse"
    higher_is_better = True
    unit = "score"

    def compute(self, output: StageOutput, sample: EvalSample) -> MetricResult:
        expected = extract_images(sample.ground_truth.get("markdown", ""))
        if not expected:
            return MetricResult(
                self.metric_id,
                1.0,
                {
                    "sample_id": sample.sample_id,
                    "image_extraction_rate": 1.0,
                    "image_anchor_accuracy": 1.0,
                    "image_score": 100.0,
                    "no_expected_images": True,
                },
            )
        if not output.success or not output.payload:
            return MetricResult(self.metric_id, 0.0, {"sample_id": sample.sample_id, "skipped": True})
        actual = extract_images(output.payload)
        extraction_rate = min(round(len(actual) / len(expected), 4), 1.0)
        anchor_matches = _count_anchor_matches(expected, actual)
        anchor_accuracy = round(anchor_matches / len(expected), 4)
        score = round(0.4 * extraction_rate + 0.6 * anchor_accuracy, 4)
        return MetricResult(
            metric_id=self.metric_id,
            value=score,
            detail={
                "sample_id": sample.sample_id,
                "expected_image_count": len(expected),
                "actual_image_count": len(actual),
                "anchor_match_count": anchor_matches,
                "image_extraction_rate": extraction_rate,
                "image_anchor_accuracy": anchor_accuracy,
                "image_score": round(score * 100, 2),
            },
        )


def _count_anchor_matches(expected: list[ImageAnchor], actual: list[ImageAnchor]) -> int:
    matched = 0
    used: set[int] = set()
    for index, expected_item in enumerate(expected):
        for actual_index, actual_item in enumerate(actual):
            if actual_index in used:
                continue
            if _anchors_match(expected_item, actual_item, expected_index=index, actual_index=actual_index):
                matched += 1
                used.add(actual_index)
                break
    return matched


def _anchors_match(
    expected: ImageAnchor,
    actual: ImageAnchor,
    expected_index: int,
    actual_index: int,
) -> bool:
    if expected.nearest_heading:
        if expected.nearest_heading != actual.nearest_heading:
            return False
        return True
    if expected.alt and expected.alt == actual.alt:
        return True
    # If no stronger context survives parser style differences, order is a
    # reasonable fallback for images extracted from the same visual flow.
    return expected_index == actual_index
