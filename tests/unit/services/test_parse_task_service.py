"""
ParseTaskService 单元测试
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.parse_task_service import ParseTaskService


class TestParseTaskService:
    """ParseTaskService 单元测试"""

    @patch("src.services.parse_task_service.MarkdownEnhancementOrchestrator")
    @patch("src.services.parse_task_service.ParserFactory.get_parser")
    def test_process_sync(self, mock_get_parser, mock_orchestrator_cls):
        mock_parser = MagicMock()
        mock_parser.parse.return_value = "raw markdown"
        mock_parser.extract_metadata.return_value = {"pages_or_length": 1}
        mock_get_parser.return_value = mock_parser
        mock_orchestrator = MagicMock()
        mock_orchestrator.aenhance_markdown = AsyncMock(return_value="cleaned markdown")
        mock_orchestrator_cls.return_value = mock_orchestrator

        with patch(
            "src.services.parse_task_service.TextFormatter.clean",
            return_value="cleaned markdown",
        ) as mock_clean:
            result = ParseTaskService.process_sync(b"dummy byte content", "txt")

        mock_get_parser.assert_called_with("txt")
        mock_parser.parse.assert_called_with(b"dummy byte content")
        mock_clean.assert_any_call("raw markdown")
        assert result["markdown"] == "cleaned markdown"
        assert result["metadata"]["pages_or_length"] == 1
        assert result["metadata"]["markdown_enhanced"] is False
        assert "time_cost_ms" in result
        assert isinstance(result["time_cost_ms"], int)

    @patch("src.services.parse_task_service.MarkdownEnhancementOrchestrator")
    @patch("src.services.parse_task_service.ParserFactory.get_parser")
    async def test_aprocess_should_parse_clean_enhance_and_return_metadata(
        self,
        mock_get_parser,
        mock_orchestrator_cls,
    ):
        mock_parser = MagicMock()
        mock_parser.parse.return_value = " raw markdown "
        mock_parser.extract_metadata.return_value = {"pages_or_length": 2}
        mock_get_parser.return_value = mock_parser
        mock_orchestrator = MagicMock()
        mock_orchestrator.aenhance_markdown = AsyncMock(return_value=" enhanced markdown ")
        mock_orchestrator_cls.return_value = mock_orchestrator

        with patch(
            "src.services.parse_task_service.TextFormatter.clean",
            side_effect=["cleaned markdown", "enhanced markdown"],
        ) as mock_clean:
            result = await ParseTaskService.aprocess(
                b"file bytes",
                "pdf",
                source_file="source.pdf",
                backend="naive",
                image_bucket="image-bucket",
            )

        mock_get_parser.assert_called_once_with(
            "pdf",
            backend="naive",
            image_bucket="image-bucket",
        )
        mock_parser.parse.assert_called_once_with(b"file bytes")
        mock_orchestrator.aenhance_markdown.assert_awaited_once_with(
            "cleaned markdown",
            source_file="source.pdf",
        )
        assert mock_clean.call_count == 2
        assert result["markdown"] == "enhanced markdown"
        assert result["metadata"] == {
            "pages_or_length": 2,
            "markdown_enhanced": True,
        }
        assert isinstance(result["time_cost_ms"], int)

    @patch("src.services.parse_task_service.MarkdownEnhancementOrchestrator")
    @patch("src.services.parse_task_service.ParserFactory.get_parser")
    async def test_aprocess_should_mark_not_enhanced_when_markdown_unchanged(
        self,
        mock_get_parser,
        mock_orchestrator_cls,
    ):
        mock_parser = MagicMock()
        mock_parser.parse.return_value = "markdown"
        mock_parser.extract_metadata.return_value = {}
        mock_get_parser.return_value = mock_parser
        mock_orchestrator = MagicMock()
        mock_orchestrator.aenhance_markdown = AsyncMock(return_value="markdown")
        mock_orchestrator_cls.return_value = mock_orchestrator

        with patch(
            "src.services.parse_task_service.TextFormatter.clean",
            return_value="markdown",
        ):
            result = await ParseTaskService.aprocess(b"file bytes", "txt")

        assert result["metadata"]["markdown_enhanced"] is False

    @patch("src.services.parse_task_service.ParserFactory.get_parser")
    async def test_aprocess_should_propagate_parser_error(self, mock_get_parser):
        mock_parser = MagicMock()
        mock_parser.parse.side_effect = ValueError("invalid file")
        mock_get_parser.return_value = mock_parser

        with pytest.raises(ValueError, match="invalid file"):
            await ParseTaskService.aprocess(b"broken bytes", "txt")

    async def test_process_sync_should_reject_running_event_loop(self):
        with pytest.raises(RuntimeError, match="must not be called inside a running event loop"):
            ParseTaskService.process_sync(b"file bytes", "txt")
