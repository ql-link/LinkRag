"""
ParseTaskService 单元测试
"""
from unittest.mock import AsyncMock, MagicMock, patch

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
