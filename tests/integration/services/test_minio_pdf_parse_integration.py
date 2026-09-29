"""
MinIO PDF 解析链路集成测试

将本用例生成的 PDF 上传到隔离 MinIO 路径，再**流式下载**到 PARSE_TEMP_DIR，
走本地解析链路生成 Markdown 并上传。下载-解析-清理顺序与生产流水线一致。
"""

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest

from src.config import settings
from src.core.pipeline.parse_task import temp_workspace
from src.core.parse_task_service import ParseTaskService
from src.services.storage.factory import StorageFactory

PDF_PARSE_CASES = [
    pytest.param(True, id="pdf-with-image"),
    pytest.param(False, id="text-only-pdf"),
]


def _pdf_fixture(expect_images: bool) -> bytes:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 72), "PDF parse integration fixture")
        if expect_images:
            image_module = pytest.importorskip("PIL.Image")
            image = image_module.new("RGB", (96, 96))
            image.putdata([
                ((x * 17 + y * 13) % 256, (x * 29 + y * 7) % 256, (x * 3 + y * 41) % 256)
                for y in range(96) for x in range(96)
            ])
            output = BytesIO()
            image.save(output, format="PNG")
            page.insert_image(fitz.Rect(72, 100, 240, 268), stream=output.getvalue())
        return doc.tobytes()
    finally:
        doc.close()


@pytest.mark.integration
@pytest.mark.skipif(settings.STORAGE_TYPE.lower() != "minio", reason="当前存储不是 MinIO")
@pytest.mark.parametrize(
    "expect_images",
    PDF_PARSE_CASES,
)
async def test_parse_pdf_from_minio_and_upload_markdown(
    monkeypatch,
    expect_images,
):
    monkeypatch.setattr(settings, "MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT", False)
    monkeypatch.setattr(settings, "MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT", False)

    storage = StorageFactory.get_storage()
    prefix = f"integration/pdf-parse/{uuid4().hex}/"
    source_object_key = prefix + "source.pdf"
    target_object_key = prefix + "result.md"
    source_bucket = target_bucket = settings.MINIO_PRIVATE_BUCKET
    try:
        storage.upload_bytes(source_bucket, source_object_key, _pdf_fixture(expect_images), "application/pdf")
        # 与生产 pipeline 一致：流式下载到临时文件，验证完后立即清理。
        temp_dir = Path(settings.PARSE_TEMP_DIR)
        temp_dir.mkdir(parents=True, exist_ok=True)
        source_path = temp_workspace.create_temp_file("integ", temp_dir)
    except Exception:
        storage.remove_prefix(source_bucket, prefix)
        raise
    try:
        storage.download_to_path(
            bucket=source_bucket,
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
            image_bucket=target_bucket,
            image_prefix=target_object_key,
            storage=storage,
        )
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
            bucket=target_bucket,
            object_key=target_object_key,
            content=markdown.encode("utf-8"),
            content_type="text/markdown; charset=utf-8",
        )

    # 验证 markdown 已成功落到对象存储：再次流式下载到独立临时路径并比对。
        verify_path = temp_workspace.create_temp_file("integ-verify", temp_dir)
        try:
            storage.download_to_path(
                bucket=target_bucket,
                object_key=target_object_key,
                dst=verify_path,
            )
            uploaded = verify_path.read_text(encoding="utf-8")
        finally:
            temp_workspace.safe_unlink(verify_path)
        assert uploaded == markdown
    finally:
        temp_workspace.safe_unlink(source_path)
        storage.remove_prefix(source_bucket, prefix)
