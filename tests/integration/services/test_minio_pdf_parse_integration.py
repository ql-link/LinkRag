"""
MinIO PDF 解析链路集成测试

从指定 MinIO 源路径**流式下载** PDF 到 PARSE_TEMP_DIR 临时文件，走本地解析链路生成
Markdown，并上传到目标路径。下载-解析-清理顺序与生产 ParseTaskPipeline 保持一致。
"""

from pathlib import Path

import pytest

from src.config import settings
from src.core.pipeline.parse_task import temp_workspace
from src.services.parse_task_service import ParseTaskService
from src.services.storage.factory import StorageFactory

SOURCE_BUCKET = "rag-raw"
TARGET_BUCKET = "rag-md"

PDF_PARSE_CASES = [
    pytest.param(
        "10002/10003/2026/04/23/EasyLive评论架构升级.pdf",
        "10002/10003/2026/04/23/EasyLive评论架构升级.md",
        True,
        id="easylive-comment-architecture",
    ),
    pytest.param(
        "raw/2026/04/21/10003/10万级用户数据日更与定向推送系统的可靠性设计.pdf",
        "raw/2026/04/21/10003/10万级用户数据日更与定向推送系统的可靠性设计.md",
        False,
        id="daily-user-push-reliability",
    ),
]


@pytest.mark.integration
@pytest.mark.skipif(settings.STORAGE_TYPE.lower() != "minio", reason="当前存储不是 MinIO")
@pytest.mark.parametrize(
    ("source_object_key", "target_object_key", "expect_images"),
    PDF_PARSE_CASES,
)
async def test_parse_pdf_from_minio_and_upload_markdown(
    monkeypatch,
    source_object_key,
    target_object_key,
    expect_images,
):
    monkeypatch.setattr(settings, "MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT", False)
    monkeypatch.setattr(settings, "MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT", False)

    storage = StorageFactory.get_storage()

    # 与生产 pipeline 一致：流式下载到临时文件，验证完后立即清理。
    temp_dir = Path(settings.PARSE_TEMP_DIR)
    temp_workspace.ensure_clean_on_startup(temp_dir)
    source_path = temp_workspace.create_temp_file("integ", temp_dir)
    try:
        storage.download_to_path(
            bucket=SOURCE_BUCKET,
            object_key=source_object_key,
            dst=source_path,
        )
        assert source_path.stat().st_size > 0
        with open(source_path, "rb") as fp:
            head = fp.read(4)
        assert head == b"%PDF"

        result = await ParseTaskService.aprocess(
            source_path,
            "pdf",
            source_file=source_object_key,
            backend="naive",
            image_bucket=TARGET_BUCKET,
            image_prefix=target_object_key,
            storage=storage,
        )
    finally:
        temp_workspace.safe_unlink(source_path)
    markdown = result["markdown"]
    image_assets = result["metadata"]["image_assets"]

    assert markdown.strip()
    assert result["metadata"]["pages_or_length"] > 0
    assert isinstance(result["time_cost_ms"], int)
    assert "intentionally omitted" not in markdown

    if expect_images:
        assert image_assets
        assert "![" in markdown and "](" in markdown

    assert all("/image/" in asset["object_key"] for asset in image_assets)
    assert all("-render." not in asset["object_key"] for asset in image_assets)

    storage.upload_bytes(
        bucket=TARGET_BUCKET,
        object_key=target_object_key,
        content=markdown.encode("utf-8"),
        content_type="text/markdown; charset=utf-8",
    )

    # 验证 markdown 已成功落到对象存储：再次流式下载到独立临时路径并比对。
    verify_path = temp_workspace.create_temp_file("integ-verify", temp_dir)
    try:
        storage.download_to_path(
            bucket=TARGET_BUCKET,
            object_key=target_object_key,
            dst=verify_path,
        )
        uploaded = verify_path.read_text(encoding="utf-8")
    finally:
        temp_workspace.safe_unlink(verify_path)

    assert uploaded == markdown
