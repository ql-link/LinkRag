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
    EvaluableRegistry.register(
        ParserAdapter(
            "pdf",
            name="parser.pdf.mineru",
            backend="mineru",
        )
    )
    EvaluableRegistry.register(
        ParserAdapter(
            "pdf",
            name="parser.pdf.naive",
            backend="naive",
        )
    )
