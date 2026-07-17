"""运行时用量上报不允许空/非正 config_id 进入后台任务。"""

from unittest.mock import MagicMock

import pytest

from src.services import usage_reporter


@pytest.mark.parametrize("config_id", [None, 0, -1, True])
def test_nowait_rejects_invalid_config_id_before_scheduling(monkeypatch, config_id):
    get_loop = MagicMock(side_effect=AssertionError("must not schedule"))
    monkeypatch.setattr(usage_reporter.asyncio, "get_running_loop", get_loop)

    usage_reporter.report_usage_nowait(
        user_id=7,
        provider_type="openai",
        model_name="m",
        stage="chat",
        operation="generate",
        config_id=config_id,
    )

    get_loop.assert_not_called()
