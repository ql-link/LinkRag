from src.evaluation.contracts.store import EvalRun, EvalRunSummary
from src.evaluation.reporters.html_reporter import HtmlReporter


def test_html_reporter_should_render_core_sections():
    run = EvalRun(
        summary=EvalRunSummary(
            run_id="run-1",
            dataset_name="multi_source_parser_eval",
            pipeline_config="[]",
            created_at=1.0,
            status="done",
            sample_count=1,
            success_count=1,
        ),
        metrics=[
            {"metric_id": "parser.quality.total_score", "value": 91.2, "detail": {}},
            {"metric_id": "parser.stability.success_rate", "value": 1.0, "detail": {}},
        ],
        sample_outputs=[
            {
                "sample_id": "s1",
                "evaluable_name": "parser.pdf.naive",
                "success": True,
                "elapsed_ms": 12,
            }
        ],
        extra={
            "parsed_results": [
                {
                    "sample_id": "s1",
                    "evaluable_name": "parser.pdf.naive",
                    "parsed_markdown_key": "reports/d/r/parsed/s1/parser/parsed.md",
                }
            ],
            "archives": {
                "best_top3": [],
                "worst_top3": [],
            },
        },
    )

    content, fmt, content_type = HtmlReporter(output_dir=None).render_bytes(run)

    html = content.decode("utf-8")
    assert fmt == "html"
    assert content_type == "text/html; charset=utf-8"
    assert "多源文件解析评估报告" in html
    assert "解析结果引用" in html
    assert "样本明细" in html
