"""
MinIO PDF 解析链路集成测试

从指定 MinIO 源路径读取 PDF，走本地解析链路生成 Markdown，并上传到目标路径。
"""

import pytest

from src.config import settings
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
SOURCE_OBJECT_KEY = "10002/10003/2026/04/23/EasyLive评论架构升级.pdf"
TARGET_BUCKET = "rag-md"
TARGET_OBJECT_KEY = "10002/10003/2026/04/23/EasyLive评论架构升级.md"


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
async def test_parse_pdf_from_minio_and_upload_markdown(monkeypatch):
    monkeypatch.setattr(settings, "MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT", False)
    monkeypatch.setattr(settings, "MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT", False)

    storage = StorageFactory.get_storage()
    file_bytes = storage.download_bytes(
        bucket=SOURCE_BUCKET,
        object_key=source_object_key,
        object_key=SOURCE_OBJECT_KEY,
    )

    assert file_bytes
    assert file_bytes.startswith(b"%PDF")

    result = await ParseTaskService.aprocess(
        file_bytes,
        "pdf",
        source_file=source_object_key,
        backend="naive",
        image_bucket=TARGET_BUCKET,
        image_prefix=target_object_key,
        source_file=SOURCE_OBJECT_KEY,
        backend="naive",
        image_bucket=TARGET_BUCKET,
        image_prefix=TARGET_OBJECT_KEY,
        storage=storage,
    )
    markdown = result["markdown"]

    assert markdown.strip()
    assert result["metadata"]["pages_or_length"] > 0
    assert isinstance(result["time_cost_ms"], int)
    if expect_images:
        assert result["metadata"]["image_assets"]
    assert result["metadata"]["image_assets"]
    assert all("/image/" in asset["object_key"] for asset in result["metadata"]["image_assets"])
    assert all(
        "-render." not in asset["object_key"] for asset in result["metadata"]["image_assets"]
    )
    assert "intentionally omitted" not in markdown
    if expect_images:
        assert "![" in markdown and "](" in markdown

    storage.upload_bytes(
        bucket=TARGET_BUCKET,
        object_key=target_object_key,
    assert "![" in markdown and "](" in markdown

    storage.upload_bytes(
        bucket=TARGET_BUCKET,
        object_key=TARGET_OBJECT_KEY,
        content=markdown.encode("utf-8"),
        content_type="text/markdown; charset=utf-8",
    )
    uploaded = storage.download_bytes(
        bucket=TARGET_BUCKET,
        object_key=target_object_key,
        object_key=TARGET_OBJECT_KEY,
    )

    assert uploaded.decode("utf-8") == markdown
