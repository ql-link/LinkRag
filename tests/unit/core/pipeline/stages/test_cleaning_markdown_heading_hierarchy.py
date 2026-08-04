# -*- coding: utf-8 -*-
"""CleaningStage native-Markdown heading hierarchy integration tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import settings
from src.core.markdown_parser import MarkdownParser
from src.core.markdown_parser.heading_hierarchy import (
    GateDecision,
    HeadingGateReason,
    HeadingHierarchyResult,
    HeadingMetrics,
)
from src.core.mq.messages.parse_task import ParseTaskPayload
from src.core.pipeline.parse_task.stages.cleaning import CleaningStage
from src.core.pipeline.parse_task.stages.context import StageContext


def _payload(file_type: str, *, source_object_key: str = "uploads/native.md"):
    return ParseTaskPayload(
        task_id="task-heading",
        original_file_id=3,
        document_parse_file_id=4,
        user_id=7,
        dataset_id=8,
        file_type=file_type,
        source_bucket=settings.MINIO_RAW_BUCKET,
        source_object_key=source_object_key,
        source_filename="native.md",
        md_bucket="legacy",
        md_object_key="parsed/native.md",
    )


def _heading_result(markdown: str) -> HeadingHierarchyResult:
    return HeadingHierarchyResult(
        markdown=markdown,
        parse_result=MarkdownParser().parse(markdown, source_file="native.md"),
        decision=GateDecision(
            should_generate=True,
            reason=HeadingGateReason.NO_HEADINGS,
            metrics=HeadingMetrics(
                total_tokens=600,
                heading_count=0,
                distinct_heading_levels=(),
                tokens_per_heading=None,
                hierarchy_clue_count=0,
            ),
            existing_headings=(),
            candidate_insert_positions=(),
        ),
        applied=True,
        insertion_count=1,
    )


def _build_stage_and_context(payload, markdown: str, tmp_path, events: list[str]):
    services = MagicMock()
    services.source_io.should_skip_source_download.return_value = False

    def download_to_path(_payload, path):
        events.append("download")
        path.write_text(markdown, encoding="utf-8")

    def upload_markdown(_payload, uploaded_markdown):
        events.append("upload")
        assert uploaded_markdown.startswith("# 自动标题\n")

    async def upload_md_images(value, _payload):
        events.append("base64")
        return value

    services.source_io.download_to_path.side_effect = download_to_path
    services.source_io.upload_markdown.side_effect = upload_markdown
    services.upload_md_images = AsyncMock(side_effect=upload_md_images)
    services.enhance_markdown_raw_images = AsyncMock(side_effect=lambda value, *_: value)
    services.parse_file = AsyncMock(side_effect=AssertionError("must not parse native Markdown"))

    enhancement = SimpleNamespace(
        enable_heading_hierarchy=True,
        enable_image_enhancement=False,
    )
    resolved_chat = SimpleNamespace(config_id=99)
    execution_context = SimpleNamespace(
        config=SimpleNamespace(enhancement=enhancement),
        enhancement_chat=resolved_chat,
    )
    ctx = StageContext(
        payload=payload,
        log_record=MagicMock(),
        pipeline_record=MagicMock(),
        db=MagicMock(),
        execution_context=execution_context,
    )
    stage = CleaningStage(
        services,
        repository=MagicMock(),
        log_repository=MagicMock(),
    )
    source_path = tmp_path / f"source.{payload.file_type.lower()}"
    return stage, ctx, services, enhancement, resolved_chat, source_path


@pytest.mark.parametrize("file_type", ["md", "markdown", "MD"])
@pytest.mark.asyncio
async def test_native_markdown_runs_heading_once_before_direct_upload(
    monkeypatch, tmp_path, file_type
):
    import src.core.pipeline.parse_task.stages.cleaning as cleaning_module

    events: list[str] = []
    payload = _payload(file_type)
    stage, ctx, services, enhancement, resolved_chat, source_path = _build_stage_and_context(
        payload,
        "正文第一段\n\n正文第二段",
        tmp_path,
        events,
    )
    monkeypatch.setattr(
        cleaning_module.temp_workspace,
        "create_temp_file",
        lambda *args, **kwargs: source_path,
    )

    async def process_heading(markdown, **kwargs):
        events.append("heading")
        assert kwargs == {
            "enhancement_config": enhancement,
            "source_file": "native.md",
            "user_id": 7,
            "resolved_model": resolved_chat,
        }
        return _heading_result(f"# 自动标题\n{markdown}")

    process = AsyncMock(side_effect=process_heading)
    monkeypatch.setattr(
        cleaning_module,
        "aprocess_existing_markdown_heading_hierarchy",
        process,
    )

    outcome = await stage.run(ctx)

    assert outcome.ok is True
    assert events == ["download", "base64", "heading", "upload"]
    process.assert_awaited_once()
    services.parse_file.assert_not_awaited()
    services.enhance_markdown_raw_images.assert_not_awaited()
    assert ctx.parse_result["markdown"].startswith("# 自动标题\n")
    assert ctx.parse_result["parse_result"].elements[0].metadata["heading_text"] == "自动标题"
    expected_metadata = {
        "heading_hierarchy_enabled": True,
        "heading_hierarchy_applied": True,
        "heading_hierarchy_reason": "no_headings",
        "heading_hierarchy_insertions": 1,
    }
    assert {
        key: ctx.parse_result["metadata"][key] for key in expected_metadata
    } == expected_metadata


@pytest.mark.asyncio
async def test_v1_raw_images_stay_before_heading_processing_and_upload(monkeypatch, tmp_path):
    import src.core.pipeline.parse_task.stages.cleaning as cleaning_module

    events: list[str] = []
    payload = _payload(
        "md",
        source_object_key=("markdown-assets/v1/user-7/dataset-8/file-3/source/normalized.md"),
    )
    stage, ctx, services, _, _, source_path = _build_stage_and_context(
        payload,
        "![图](tolink-raw://raw/image.png)\n\n正文",
        tmp_path,
        events,
    )
    monkeypatch.setattr(
        cleaning_module.temp_workspace,
        "create_temp_file",
        lambda *args, **kwargs: source_path,
    )

    async def enhance_raw(markdown, *_):
        events.append("raw")
        return markdown.replace("图", "已增强图片")

    async def process_heading(markdown, **kwargs):
        events.append("heading")
        assert "已增强图片" in markdown
        return _heading_result(f"# 自动标题\n{markdown}")

    services.enhance_markdown_raw_images.side_effect = enhance_raw
    monkeypatch.setattr(
        cleaning_module,
        "aprocess_existing_markdown_heading_hierarchy",
        AsyncMock(side_effect=process_heading),
    )

    outcome = await stage.run(ctx)

    assert outcome.ok is True
    assert events == ["download", "base64", "raw", "heading", "upload"]
    services.enhance_markdown_raw_images.assert_awaited_once()
    services.parse_file.assert_not_awaited()
