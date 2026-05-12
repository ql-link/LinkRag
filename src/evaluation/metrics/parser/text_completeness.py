# -*- coding: utf-8 -*-
"""Parser text completeness metrics."""
from __future__ import annotations

from src.evaluation.contracts.dataset import EvalSample
from src.evaluation.contracts.evaluable import StageOutput
from src.evaluation.contracts.metric import MetricResult

from .normalization import calculate_lcs_ratio, token_recall, tokenize_markdown_text


class TextCompletenessMetric:
    """Token recall first, LCS ratio second text completeness metric."""

    metric_id = "parser.text.completeness"
    scope = "parse"
    higher_is_better = True
    unit = "score"

    def compute(self, output: StageOutput, sample: EvalSample) -> MetricResult:
        gt_md = sample.ground_truth.get("markdown", "")
        if not gt_md or not output.success or not output.payload:
            return MetricResult(
                metric_id=self.metric_id,
                value=0.0,
                detail={
                    "sample_id": sample.sample_id,
                    "skipped": True,
                    "reason": "无 ground_truth 或解析失败",
                },
            )
        expected_tokens = tokenize_markdown_text(gt_md)
        actual_tokens = tokenize_markdown_text(output.payload)
        recall = token_recall(expected_tokens, actual_tokens)
        lcs_ratio = calculate_lcs_ratio(gt_md, output.payload)
        score = round(0.7 * recall + 0.3 * lcs_ratio, 4)
        return MetricResult(
            metric_id=self.metric_id,
            value=score,
            detail={
                "sample_id": sample.sample_id,
                "token_recall": recall,
                "lcs_ratio": lcs_ratio,
                "text_score": round(score * 100, 2),
                "expected_token_count": len(expected_tokens),
                "actual_token_count": len(actual_tokens),
            },
        )
