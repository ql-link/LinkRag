"""
ParserFactory 单元测试

验证文件类型到解析器的路由是否正确，不执行真实文件解析。
"""

from unittest.mock import MagicMock, patch

import pytest

from src.core.exceptions import UnsupportedFormatError
from src.core.parser.factory import ParserFactory


class TestParserFactory:
    @patch("src.core.parser.factory.WordParser")
    def test_get_parser_should_return_word_parser_for_docx(self, mock_word_parser_cls):
        mock_parser = MagicMock()
        mock_word_parser_cls.return_value = mock_parser

        parser = ParserFactory.get_parser("DOCX")

        assert parser is mock_parser
        mock_word_parser_cls.assert_called_once_with()

    @patch("src.core.parser.factory.PdfParser")
    def test_get_parser_should_return_pdf_parser_with_options(self, mock_pdf_parser_cls):
        mock_parser = MagicMock()
        mock_pdf_parser_cls.return_value = mock_parser

        parser = ParserFactory.get_parser(
            "pdf",
            backend="naive",
            image_bucket="image-bucket",
            image_prefix="images/task-1",
        )

        assert parser is mock_parser
        mock_pdf_parser_cls.assert_called_once_with(
            backend="naive",
            image_bucket="image-bucket",
            image_prefix="images/task-1",
        )

    @patch("src.core.parser.factory.HtmlParser")
    def test_get_parser_should_return_html_parser_for_htm(self, mock_html_parser_cls):
        mock_parser = MagicMock()
        mock_html_parser_cls.return_value = mock_parser

        parser = ParserFactory.get_parser(
            "htm",
            source_file_url="https://cdn.example.com/docs/page.html",
            image_prefix="images/task-1",
        )

        assert parser is mock_parser
        mock_html_parser_cls.assert_called_once_with(
            source_file_url="https://cdn.example.com/docs/page.html",
            image_prefix="images/task-1",
        )

    def test_get_parser_should_raise_for_unsupported_format(self):
        with pytest.raises(UnsupportedFormatError, match="不支持的格式"):
            ParserFactory.get_parser("xlsx")
