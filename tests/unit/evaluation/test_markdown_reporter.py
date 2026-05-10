from datetime import datetime
from pathlib import Path

from src.evaluation.contracts.store import EvalRun, EvalRunSummary
from src.evaluation.reporters.markdown_reporter import MarkdownReporter


def test_markdown_reporter_should_use_module_and_timestamp_filename(tmp_path: Path):
    run = _build_parse_run()

    report_path = MarkdownReporter(output_dir=str(tmp_path)).render(run)

    assert Path(report_path).name == "parse_202605102038.md"


def test_markdown_reporter_should_include_readable_summary_sections(tmp_path: Path):
    run = _build_parse_run()

    report_path = MarkdownReporter(output_dir=str(tmp_path)).render(run)
    content = Path(report_path).read_text(encoding="utf-8")

    assert "## 测试总结" in content
    assert "## 指标概览" in content
    assert "## 指标明细" in content
    assert "本次测试针对 `parse` 模块" in content
    assert "成功率为 100.00%" in content
    assert "| 指标 | 概览 |" in content
    assert "| 标题结构保留率 | 平均 75.00%" in content
    assert "解析耗时中位数为 0.01 秒，P95 为 0.03 秒" in content
    assert "| `parser.md_structure.heading_retention` | 100.00%" in content


def _build_parse_run() -> EvalRun:
    created_at = datetime(2026, 5, 10, 20, 38).timestamp()
    return EvalRun(
        summary=EvalRunSummary(
            run_id="run-1",
            dataset_name="parser_smoke",
            pipeline_config="",
            created_at=created_at,
            status="done",
            sample_count=2,
            success_count=2,
        ),
        metrics=[
            {
                "metric_id": "parser.md_structure.heading_retention",
                "value": 1.0,
                "detail": {"sample_id": "sample-1"},
            },
            {
                "metric_id": "parser.md_structure.heading_retention",
                "value": 0.5,
                "detail": {"sample_id": "sample-2"},
            },
            {
                "metric_id": "parser.stability.success_rate",
                "value": 1.0,
                "detail": {"total": 2, "success": 2},
            },
            {
                "metric_id": "parser.latency.percentiles",
                "value": {"p50": 12.3, "p95": 30.5},
                "detail": {},
            },
        ],
        extra={"stage_result.parse": {"comparison": None}},
    )
