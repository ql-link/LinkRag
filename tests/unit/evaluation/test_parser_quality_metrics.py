from src.evaluation.contracts.dataset import EvalSample
from src.evaluation.contracts.evaluable import StageOutput
from src.evaluation.metrics.parser.heading_quality import (
    HeadingCoverageMetric,
    HeadingLevelAccuracyMetric,
)
from src.evaluation.metrics.parser.image_quality import ImageQualityMetric
from src.evaluation.metrics.parser.quality_score import ParserSampleQualityMetric
from src.evaluation.metrics.parser.table_quality import TableQualityMetric
from src.evaluation.metrics.parser.text_completeness import TextCompletenessMetric


def test_text_completeness_should_score_partial_recall():
    sample = _sample("# 标题\n\n这是一个重要段落")
    output = _output("# 标题\n\n这是一个段落")

    result = TextCompletenessMetric().compute(output, sample)

    assert 0 < result.value <= 1
    assert result.detail["token_recall"] < 1


def test_heading_level_accuracy_should_allow_global_offset():
    sample = _sample("# A\n\n## B")
    output = _output("## A\n\n### B")

    result = HeadingLevelAccuracyMetric().compute(output, sample)

    assert result.value == 1.0


def test_heading_coverage_should_detect_missing_heading():
    sample = _sample("# A\n\n## B")
    output = _output("# A")

    result = HeadingCoverageMetric().compute(output, sample)

    assert result.value == 0.5


def test_image_quality_should_penalize_anchor_mismatch():
    sample = _sample("# A\n\n![one](a.png)\n\n# B\n\n![two](b.png)")
    output = _output("# A\n\n![one](a.png)\n\n![two](b.png)")

    result = ImageQualityMetric().compute(output, sample)

    assert result.detail["image_extraction_rate"] == 1.0
    assert result.detail["image_anchor_accuracy"] < 1.0


def test_table_quality_should_penalize_missing_columns():
    sample = _sample("| A | B |\n|---|---|\n| 1 | 2 |")
    output = _output("| A |\n|---|\n| 1 |")

    result = TableQualityMetric().compute(output, sample)

    assert result.value < 1.0


def test_sample_quality_should_be_zero_when_parse_failed():
    sample = _sample("# A")
    output = StageOutput(sample_id="s1", payload=None, elapsed_ms=1, success=False, error_type="Boom")

    result = ParserSampleQualityMetric().compute(output, sample)

    assert result.value == 0.0


def _sample(markdown: str) -> EvalSample:
    return EvalSample(
        sample_id="s1",
        file_path=None,
        file_type="pdf",
        ground_truth={"markdown": markdown},
    )


def _output(markdown: str) -> StageOutput:
    return StageOutput(sample_id="s1", payload=markdown, elapsed_ms=10, success=True)
