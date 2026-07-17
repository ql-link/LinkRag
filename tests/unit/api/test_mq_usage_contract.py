"""LLM 用量上报边界的 config_id-only 契约。"""

import pytest
from pydantic import ValidationError

from src.api.schemas.mq import SendUsageReportRequest
from src.models.usage_log import UsageLog


def _request(**overrides):
    values = {
        "user_id": "7",
        "provider_type": "openai",
        "model_name": "gpt-4o-mini",
        "stage": "chat",
        "operation": "generate",
        "config_id": 9,
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize("config_id", [None, 0, -1])
def test_new_usage_http_request_requires_positive_config_id(config_id):
    with pytest.raises(ValidationError):
        SendUsageReportRequest.model_validate(_request(config_id=config_id))


def test_historical_usage_row_allows_null_but_uses_numeric_id():
    historical = UsageLog(
        id="old-1",
        user_id="7",
        config_id=None,
        provider_type="openai",
        model_name="legacy",
    )
    current = UsageLog(
        id="new-1",
        user_id="7",
        config_id=9,
        provider_type="openai",
        model_name="gpt-4o-mini",
    )

    assert historical.config_id is None
    assert current.config_id == 9
