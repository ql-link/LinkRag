"""MinerU 和 Marker 后端的单元测试。

测试策略：
- MinerU: Mock HTTP 请求，验证 API 调用逻辑和降级行为
- Marker: Mock marker-pdf 库，验证模型加载和解析逻辑
- Service: 验证 backend 路由和降级链路
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from src.core.parser.pdf.backends.mineru_backend import MinerUBackend
from src.core.parser.pdf.models import PdfParseOptions
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
