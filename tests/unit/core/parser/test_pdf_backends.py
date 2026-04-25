"""MinerU 和 Marker 后端的单元测试。

测试策略：
- MinerU: Mock HTTP 请求，验证 API 调用逻辑和降级行为
- Marker: Mock marker-pdf 库，验证模型加载和解析逻辑
- Service: 验证 backend 路由和降级链路
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from src.core.parser.pdf.backends.mineru_backend import MinerUBackend
from src.core.parser.pdf.backends.naive_backend import NaivePdfBackend
from src.core.parser.pdf.models import PdfImageAsset, PdfParseOptions
from src.core.parser.pdf.service import PdfParserService

# ── MinerU Backend Tests ──────────────────────────────────────────────


class TestMinerUBackend:
    """MinerU HTTP API 后端测试。"""

    def test_returns_empty_when_api_url_not_configured(self):
        """API URL 为空时应返回空结果。"""
        backend = MinerUBackend(api_url="")
        md, assets = backend.parse(b"fake-pdf-bytes")
        assert md == ""
        assert assets == []
        assert "mineru_backend_error" in backend.metadata

    def test_returns_empty_when_api_url_is_none(self):
        """API URL 为 None 时应返回空结果。"""
        backend = MinerUBackend(api_url=None)
        md, assets = backend.parse(b"fake-pdf-bytes")
        assert md == ""

    @patch("src.core.parser.pdf.backends.mineru_backend.httpx.Client")
    def test_successful_api_call(self, mock_client_cls):
        """模拟 API 成功返回 Markdown。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "markdown": "# Test\n\nHello world",
            "parse_method": "auto",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        backend = MinerUBackend(api_url="http://localhost:8010")
        md, assets = backend.parse(b"fake-pdf-bytes")
        assert md == "# Test\n\nHello world"
        assert backend.metadata["mineru_api_status"] == 200

    @patch("src.core.parser.pdf.backends.mineru_backend.httpx.Client")
    def test_api_connection_error_returns_empty(self, mock_client_cls):
        """API 连接失败时应返回空结果。"""
        import httpx

        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        backend = MinerUBackend(api_url="http://localhost:8010")
        md, assets = backend.parse(b"fake-pdf-bytes")
        assert md == ""
        assert "mineru_backend_error" in backend.metadata

    @patch("src.core.parser.pdf.backends.mineru_backend.httpx.Client")
    def test_api_timeout_returns_empty(self, mock_client_cls):
        """API 超时时应返回空结果。"""
        import httpx

        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.TimeoutException("Timeout")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        backend = MinerUBackend(api_url="http://localhost:8010")
        md, assets = backend.parse(b"fake-pdf-bytes")
        assert md == ""
        assert "超时" in backend.metadata.get("mineru_backend_error", "")

    def test_content_list_to_markdown(self):
        """测试 content_list 结构化数据转 Markdown。"""
        backend = MinerUBackend(api_url="http://localhost:8010")
        content_list = [
            {"type": "text", "content": "# 第一章"},
            {"type": "table", "content": "<table><tr><td>A</td></tr></table>"},
            {"type": "image", "img_path": "images/fig1.png", "img_caption": "架构图"},
            {"type": "equation", "content": "E=mc^2"},
        ]
        md = backend._content_list_to_markdown(content_list)
        assert "# 第一章" in md
        assert "<table>" in md
        assert "![架构图](images/fig1.png)" in md
        assert "$E=mc^2$" in md


# ── Service Routing Tests ─────────────────────────────────────────────


class TestPdfParserServiceRouting:
    """PdfParserService 后端路由测试。"""

    def test_auto_backend_order(self):
        """auto 模式应按 MinerU→Naive 顺序。"""
        service = PdfParserService()
        order = service._build_backend_order("auto")
        assert order == ["mineru", "naive"]

    def test_mineru_backend_order(self):
        """mineru 模式应有 Naive 兜底。"""
        service = PdfParserService()
        order = service._build_backend_order("mineru")
        assert order == ["mineru", "naive"]

    def test_naive_backend_order(self):
        """naive 模式应仅有 Naive。"""
        service = PdfParserService()
        order = service._build_backend_order("naive")
        assert order == ["naive"]

    def test_create_mineru_instance_without_url_returns_none(self):
        """MinerU API URL 未配置时 _create_backend_instance 应返回 None。"""
        service = PdfParserService()
        options = PdfParseOptions(backend="mineru", mineru_api_url="")
        instance = service._create_backend_instance("mineru", options)
        assert instance is None

    def test_create_mineru_instance_with_url(self):
        """MinerU API URL 已配置时应返回 MinerUBackend 实例。"""
        service = PdfParserService()
        options = PdfParseOptions(backend="mineru", mineru_api_url="http://localhost:8010")
        instance = service._create_backend_instance("mineru", options)
        assert isinstance(instance, MinerUBackend)

    def test_create_unknown_backend_returns_none(self):
        """未知后端名称应返回 None。"""
        service = PdfParserService()
        options = PdfParseOptions(backend="unknown")
        instance = service._create_backend_instance("nonexistent", options)
        assert instance is None

    def test_build_image_object_key_should_store_under_md_sibling_image_dir(self):
        service = PdfParserService()

        object_key = service._build_image_object_key(
            "10002/10003/2026/04/23/EasyLive评论架构升级.md",
            "page-001-image-01.png",
        )

        assert object_key == (
            "10002/10003/2026/04/23/image/" "EasyLive评论架构升级/page-001-image-01.png"
        )

    def test_inject_image_references_should_replace_naive_placeholders(self):
        service = PdfParserService()
        markdown = (
            "## 第 1 页\n\n"
            "**==> picture page 1 image 1 intentionally omitted <==**\n\n"
            "正文内容"
        )
        image_assets = [
            MagicMock(page_number=1, index=1, url="http://minio/image/page-001-image-01.png"),
        ]

        injected = service._inject_image_references(markdown, "naive", image_assets)

        assert "http://minio/image/page-001-image-01.png" in injected
        assert "intentionally omitted" not in injected

    def test_inject_image_references_should_match_naive_placeholder_by_aspect_ratio(self):
        service = PdfParserService()
        markdown = (
            "**==> picture [740 x 299] intentionally omitted <==**\n\n"
            "**==> picture [744 x 171] intentionally omitted <==**\n\n"
            "**==> picture [740 x 632] intentionally omitted <==**"
        )
        image_assets = [
            PdfImageAsset(
                page_number=1,
                index=1,
                object_key="page-001-region-01.png",
                url="http://minio/flow.png",
                width=1518,
                height=634,
            ),
            PdfImageAsset(
                page_number=4,
                index=1,
                object_key="page-004-region-01.png",
                url="http://minio/architecture.png",
                width=1516,
                height=1300,
            ),
        ]

        injected = service._inject_image_references(markdown, "naive", image_assets)

        assert "http://minio/flow.png" in injected
        assert "http://minio/architecture.png" in injected
        assert "[744 x 171]" not in injected
        assert injected.index("http://minio/flow.png") < injected.index(
            "http://minio/architecture.png"
        )

    @patch("src.core.parser.pdf.service.fitz.open")
    def test_upload_images_should_extract_naive_image_blocks_without_page_render(
        self, mock_fitz_open
    ):
        service = PdfParserService()
        storage = MagicMock()
        storage.build_object_url.side_effect = lambda bucket, key: f"http://minio/{bucket}/{key}"
        options = PdfParseOptions(
            backend="naive",
            image_bucket="rag-md",
            image_prefix="10002/10003/doc.md",
            storage=storage,
        )
        rng = np.random.default_rng(1)
        image = rng.integers(0, 255, size=(120, 120, 3), dtype=np.uint8)
        success, encoded = cv2.imencode(".png", image)
        assert success
        image_bytes = encoded.tobytes()
        page = MagicMock()
        page.rect.width = 600
        page.rect.height = 800
        page.get_images.return_value = []
        page.get_text.return_value = {
            "blocks": [
                {
                    "type": 1,
                    "bbox": [10, 20, 30, 40],
                    "image": image_bytes,
                    "ext": "png",
                }
            ]
        }
        page.get_pixmap.side_effect = AssertionError("naive must not render full pages")
        mock_fitz_open.return_value = [page]

        image_assets = service._upload_images(
            b"pdf-bytes",
            options,
            backend="naive",
            placeholder_count=1,
            binary_assets=[],
        )

        assert len(image_assets) == 1
        assert image_assets[0].object_key == "10002/10003/image/doc/page-001-block-01.png"
        storage.upload_bytes.assert_called_once_with(
            bucket="rag-md",
            object_key="10002/10003/image/doc/page-001-block-01.png",
            content=image_bytes,
            content_type="image/png",
        )

    @patch("src.core.parser.pdf.service.fitz.open")
    def test_upload_images_should_ignore_tiny_naive_blocks_and_crop_visual_regions(
        self, mock_fitz_open
    ):
        service = PdfParserService()
        storage = MagicMock()
        storage.build_object_url.side_effect = lambda bucket, key: f"http://minio/{bucket}/{key}"
        options = PdfParseOptions(
            backend="naive",
            image_bucket="rag-md",
            image_prefix="10002/10003/doc.md",
            storage=storage,
        )

        tiny = np.zeros((11, 11, 3), dtype=np.uint8)
        success, tiny_encoded = cv2.imencode(".png", tiny)
        assert success

        rendered = np.full((900, 1200, 3), 255, dtype=np.uint8)
        cv2.rectangle(rendered, (260, 180), (940, 650), (0, 0, 0), 5)
        for y in range(240, 620, 70):
            cv2.line(rendered, (310, y), (900, y), (0, 0, 0), 4)
        for x in range(360, 900, 120):
            cv2.line(rendered, (x, 230), (x, 610), (0, 0, 0), 3)

        pix = MagicMock()
        pix.samples = rendered.tobytes()
        pix.height = rendered.shape[0]
        pix.width = rendered.shape[1]
        pix.n = 3

        page = MagicMock()
        page.rect.width = 600
        page.rect.height = 800
        page.get_images.return_value = []
        page.get_text.return_value = {
            "blocks": [
                {
                    "type": 1,
                    "bbox": [10, 20, 21, 31],
                    "image": tiny_encoded.tobytes(),
                    "ext": "png",
                }
            ]
        }
        page.get_pixmap.return_value = pix
        mock_fitz_open.return_value = [page]

        image_assets = service._upload_images(
            b"pdf-bytes",
            options,
            backend="naive",
            placeholder_count=1,
            binary_assets=[],
        )

        assert len(image_assets) == 1
        assert image_assets[0].object_key == "10002/10003/image/doc/page-001-region-01.png"
        uploaded = storage.upload_bytes.call_args.kwargs
        assert uploaded["object_key"] == "10002/10003/image/doc/page-001-region-01.png"
        assert uploaded["content_type"] == "image/png"
        assert len(uploaded["content"]) > len(tiny_encoded.tobytes())

    def test_detect_visual_regions_should_exclude_table_bboxes(self):
        service = PdfParserService()
        rendered = np.full((900, 1200, 3), 255, dtype=np.uint8)
        cv2.rectangle(rendered, (260, 180), (940, 650), (0, 0, 0), 5)
        for y in range(240, 620, 70):
            cv2.line(rendered, (310, y), (900, y), (0, 0, 0), 4)
        for x in range(360, 900, 120):
            cv2.line(rendered, (x, 230), (x, 610), (0, 0, 0), 3)

        regions = service._detect_visual_regions(
            rendered,
            excluded_bboxes=[(240, 160, 720, 520)],
        )

        assert regions == []


class TestNaivePdfBackend:
    def test_remove_picture_text_blocks_should_drop_pymupdf4llm_picture_ocr(self):
        backend = NaivePdfBackend()
        markdown = (
            "# 标题\n\n"
            "**----- Start of picture text -----**<br>\n"
            "图片内 OCR 文本<br>\n"
            "更多图片文字<br>\n"
            "**----- End of picture text -----**<br>\n\n"
            "正文内容"
        )

        cleaned = backend._remove_picture_text_blocks(markdown)

        assert "Start of picture text" not in cleaned
        assert "End of picture text" not in cleaned
        assert "图片内 OCR 文本" not in cleaned
        assert "# 标题" in cleaned
        assert "正文内容" in cleaned

    def test_normalize_numbered_lists_should_split_inline_items(self):
        backend = NaivePdfBackend()
        markdown = (
            "假设有以下场景：有一场对话，一共发生了 4 次交互：\n\n"
            "- 一\n\n"
            "- 1. 张三 发了一条主评论：“这视频真赞！” （ 级评论 ）\n\n"
            "2. 李四 回复张三：“我也觉得。” （ 二级评论 ） "
            "3. 王五 回复李四：“你觉得哪儿好？” （ 三级评论 ） "
            "4. 赵六 回复王五：“我觉得运镜好。” （ 四级评论 ）"
        )

        cleaned = backend._normalize_numbered_lists(markdown)

        assert "- 一" not in cleaned
        assert "1. 张三 发了一条主评论：“这视频真赞！”（一级评论）" in cleaned
        assert "\n2. 李四 回复张三：“我也觉得。”（二级评论）" in cleaned
        assert "\n3. 王五 回复李四：“你觉得哪儿好？”（三级评论）" in cleaned
        assert "\n4. 赵六 回复王五：“我觉得运镜好。”（四级评论）" in cleaned

    def test_merge_split_tables_should_join_adjacent_tables_with_same_header(self):
        backend = NaivePdfBackend()
        markdown = (
            "|字段名|类型|核心作用|备注|\n"
            "|---|---|---|---|\n"
            "|comment_id|BIGINT|唯一主键|使用雪花算法生成|\n"
            "|video_id|BIGINT|关联视频|建立普通索引|\n"
            "\n"
            "|字段名|类型|核心作用|备注|\n"
            "|---|---|---|---|\n"
            "|root_id|BIGINT|根评论聚<br>合|一级评论设为 0|\n"
            "|parent_id|BIGINT|父级溯源|记录回复评论|\n"
        )

        merged = backend._merge_split_tables(markdown)

        assert merged.count("|字段名|类型|核心作用|备注|") == 1
        assert merged.count("|---|---|---|---|") == 1
        assert "|comment_id|BIGINT|唯一主键|使用雪花算法生成|" in merged
        assert "|parent_id|BIGINT|父级溯源|记录回复评论|" in merged

    def test_merge_split_tables_should_not_join_different_headers(self):
        backend = NaivePdfBackend()
        markdown = (
            "|字段名|类型|核心作用|备注|\n"
            "|---|---|---|---|\n"
            "|comment_id|BIGINT|唯一主键|使用雪花算法生成|\n"
            "\n"
            "|容器名称|存储内容|维护策略|\n"
            "|---|---|---|\n"
            "|video:hot_zset|热门评论|固定容量|\n"
        )

        merged = backend._merge_split_tables(markdown)

        assert "|字段名|类型|核心作用|备注|" in merged
        assert "|容器名称|存储内容|维护策略|" in merged
        assert "|---|---|---|---|" in merged
        assert "|---|---|---|" in merged

    def test_extract_page_markdown_should_keep_image_placeholder_in_order(self):
        backend = NaivePdfBackend()
        page = MagicMock()
        page.get_text.return_value = {
            "blocks": [
                {
                    "type": 0,
                    "bbox": [0, 0, 10, 10],
                    "lines": [{"spans": [{"text": "标题"}]}],
                },
                {
                    "type": 1,
                    "bbox": [0, 20, 10, 30],
                },
                {
                    "type": 0,
                    "bbox": [0, 40, 10, 50],
                    "lines": [{"spans": [{"text": "正文"}]}],
                },
            ]
        }

        markdown = backend._extract_page_markdown(0, page)

        assert "标题" in markdown
        assert "**==> picture page 1 image 1 intentionally omitted <==**" in markdown
        assert "正文" in markdown
