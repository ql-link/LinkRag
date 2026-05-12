# -*- coding: utf-8 -*-
"""Parser table quality metrics."""
from __future__ import annotations

from src.evaluation.contracts.dataset import EvalSample
from src.evaluation.contracts.evaluable import StageOutput
from src.evaluation.contracts.metric import MetricResult

from .structure_extractors import TableBlock, extract_tables


class TableQualityMetric:
    metric_id = "parser.table.quality"
    scope = "parse"
    higher_is_better = True
    unit = "score"

    def compute(self, output: StageOutput, sample: EvalSample) -> MetricResult:
        expected = extract_tables(sample.ground_truth.get("markdown", ""))
        if not expected:
            return MetricResult(
                self.metric_id,
                1.0,
                {
                    "sample_id": sample.sample_id,
                    "table_detection_rate": 1.0,
                    "table_structure_accuracy": 1.0,
                    "table_score": 100.0,
                    "no_expected_tables": True,
                },
            )
        if not output.success or not output.payload:
            return MetricResult(self.metric_id, 0.0, {"sample_id": sample.sample_id, "skipped": True})
        actual = extract_tables(output.payload)
        pairs = _match_tables(expected, actual)
        detection_rate = round(len(pairs) / len(expected), 4)
        structure_accuracy = round(
            sum(_table_similarity(exp, act) for exp, act in pairs) / len(expected),
            4,
        )
        score = round(0.3 * detection_rate + 0.7 * structure_accuracy, 4)
        return MetricResult(
            metric_id=self.metric_id,
            value=score,
            detail={
                "sample_id": sample.sample_id,
                "expected_table_count": len(expected),
                "actual_table_count": len(actual),
                "matched_table_count": len(pairs),
                "table_detection_rate": detection_rate,
                "table_structure_accuracy": structure_accuracy,
                "table_score": round(score * 100, 2),
            },
        )


def _match_tables(
    expected: list[TableBlock],
    actual: list[TableBlock],
) -> list[tuple[TableBlock, TableBlock]]:
    pairs: list[tuple[TableBlock, TableBlock]] = []
    used: set[int] = set()
    for expected_index, expected_item in enumerate(expected):
        best_index = None
        best_score = 0.0
        for actual_index, actual_item in enumerate(actual):
            if actual_index in used:
                continue
            score = _table_similarity(expected_item, actual_item)
            if expected_item.nearest_heading and expected_item.nearest_heading == actual_item.nearest_heading:
                score += 0.2
            if expected_index == actual_index:
                score += 0.1
            if score > best_score:
                best_score = score
                best_index = actual_index
        if best_index is not None and best_score > 0.35:
            used.add(best_index)
            pairs.append((expected_item, actual[best_index]))
    return pairs


def _table_similarity(expected: TableBlock, actual: TableBlock) -> float:
    row_score = _ratio(actual.row_count, expected.row_count)
    column_score = _ratio(actual.column_count, expected.column_count)
    header_score = _header_similarity(expected.header_cells, actual.header_cells)
    hash_bonus = 1.0 if expected.structure_hash == actual.structure_hash else 0.0
    return round(0.35 * row_score + 0.35 * column_score + 0.2 * header_score + 0.1 * hash_bonus, 4)


def _ratio(actual: int, expected: int) -> float:
    if expected <= 0:
        return 1.0
    return min(actual / expected, 1.0)


def _header_similarity(expected: tuple[str, ...], actual: tuple[str, ...]) -> float:
    if not expected:
        return 1.0
    actual_set = set(actual)
    matched = sum(1 for cell in expected if cell in actual_set)
    return matched / len(expected)
