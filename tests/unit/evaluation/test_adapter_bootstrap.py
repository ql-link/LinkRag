from src.evaluation.adapters.bootstrap import register_builtin_evaluables
from src.evaluation.adapters.parser_adapter import ParserAdapter
from src.evaluation.adapters.registry import EvaluableRegistry
from src.evaluation.cli import _register_builtin_metrics
from src.evaluation.metrics.registry import MetricRegistry
from src.evaluation.runners.pipeline import EvalPipeline


def test_register_builtin_evaluables_should_register_parser_adapters():
    EvaluableRegistry.clear()

    register_builtin_evaluables()

    mineru = EvaluableRegistry.get("parser.pdf.mineru")
    naive = EvaluableRegistry.get("parser.pdf.naive")
    opendataloader = EvaluableRegistry.get("parser.pdf.opendataloader")
    word = EvaluableRegistry.get("parser.word")
    html = EvaluableRegistry.get("parser.html")

    assert isinstance(mineru, ParserAdapter)
    assert isinstance(naive, ParserAdapter)
    assert isinstance(opendataloader, ParserAdapter)
    assert isinstance(word, ParserAdapter)
    assert isinstance(html, ParserAdapter)
    assert mineru.stage == "parse"
    assert naive.stage == "parse"
    assert opendataloader.stage == "parse"
    assert word.stage == "parse"
    assert html.stage == "parse"


def test_register_builtin_evaluables_should_be_idempotent():
    EvaluableRegistry.clear()

    register_builtin_evaluables()
    register_builtin_evaluables()

    names = sorted(e.name for e in EvaluableRegistry.all())
    assert names == [
        "parser.pdf.mineru",
        "parser.pdf.naive",
        "parser.pdf.opendataloader",
        "parser.html",
        "parser.word",
    ]


def test_parser_only_pipeline_should_validate_with_builtin_registries():
    EvaluableRegistry.clear()
    MetricRegistry.clear()

    register_builtin_evaluables()
    _register_builtin_metrics()

    pipeline = EvalPipeline.from_yaml("configs/eval/parser_only.yaml")
    pipeline.validate(EvaluableRegistry, MetricRegistry)
