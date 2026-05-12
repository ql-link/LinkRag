# -*- coding: utf-8 -*-
"""Built-in Evaluable registration for the evaluation CLI."""
from __future__ import annotations

from src.evaluation.adapters.parser_adapter import ParserAdapter
from src.evaluation.adapters.registry import EvaluableRegistry


def register_builtin_evaluables() -> None:
    """Register built-in parser evaluables used by pipeline YAML files.

    Registration is idempotent because ``EvaluableRegistry.register`` overwrites
    an existing name with the same logical adapter.
    """
    _register_parser_adapter("pdf", "parser.pdf.mineru", backend="mineru")
    _register_parser_adapter("pdf", "parser.pdf.naive", backend="naive")
    _register_parser_adapter("pdf", "parser.pdf.opendataloader", backend="opendataloader")
    _register_parser_adapter("docx", "parser.word")
    _register_parser_adapter("html", "parser.html")


def _register_parser_adapter(file_type: str, name: str, **parser_kwargs) -> None:
    EvaluableRegistry.register(
        ParserAdapter(
            file_type,
            name=name,
            **parser_kwargs,
        )
    )
