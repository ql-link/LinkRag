# -*- coding: utf-8 -*-
"""ParseTaskService heading hierarchy integration tests."""

from types import SimpleNamespace

import pytest

from src.core.parse_task_service import ParseTaskService


class _FakeParser:
    def parse(self, source_path):
        return "正文第一段\n\n正文第二段"

    def extract_metadata(self):
        return {}


class _FakeEnhancedParseResult:
    tables = []
    images = []

    def to_markdown(self):
        return "正文第一段\n\n正文第二段"


@pytest.mark.asyncio
async def test_parse_task_service_passes_user_id_to_heading_processor(monkeypatch):
    import src.core.parse_task_service as service_module

    captured = {}

    class _FakeOrchestrator:
        async def aenhance_parse_result(self, *args, **kwargs):
            return _FakeEnhancedParseResult()

    class _FakeHeadingProcessor:
        def __init__(self, config=None):
            pass

        async def aprocess(
            self, markdown, *, source_file=None, user_id=None, resolved_model=None
        ):
            captured["markdown"] = markdown
            captured["source_file"] = source_file
            captured["user_id"] = user_id
            captured["resolved_model"] = resolved_model
            return SimpleNamespace(
                markdown=markdown,
                parse_result=SimpleNamespace(elements=[]),
                decision=SimpleNamespace(reason=SimpleNamespace(value="healthy_heading_tree")),
                applied=False,
                insertion_count=0,
            )

    monkeypatch.setattr(
        service_module.ParserFactory,
        "get_parser",
        lambda file_type, **kwargs: _FakeParser(),
    )
    monkeypatch.setattr(service_module, "MarkdownEnhancementOrchestrator", _FakeOrchestrator)
    monkeypatch.setattr(service_module, "HeadingHierarchyProcessor", _FakeHeadingProcessor)

    await ParseTaskService.aprocess(
        None,
        "pdf",
        source_file="x.pdf",
        user_id=7,
    )

    assert captured == {
        "markdown": "正文第一段\n\n正文第二段",
        "source_file": "x.pdf",
        "user_id": 7,
        "resolved_model": None,
    }
