"""``/llm`` 边界只接受全局 config_id，拒绝旧来源/模型覆盖字段。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.api.routes.llm import (
    EmbedRequest,
    GenerateRequest,
    OcrRequest,
    RerankRequest,
    _coerce_int,
    _resolve_provider,
    extract_text_from_image,
)
from src.core.llm.exceptions import LLMConfigNotFoundError


def test_coerce_int_valid():
    assert _coerce_int("123", "X-User-Id") == 123


@pytest.mark.parametrize("value", ["abc", ""])
def test_coerce_int_rejects_invalid_user_id(value):
    with pytest.raises(HTTPException) as exc:
        _coerce_int(value, "X-User-Id")
    assert exc.value.status_code == 422


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (GenerateRequest, {"config_id": 1, "prompt": "p", "config_source": "SYSTEM"}),
        (EmbedRequest, {"config_id": 1, "input": "x", "model": "legacy"}),
        (
            RerankRequest,
            {
                "config_id": 1,
                "query": "q",
                "documents": ["d"],
                "override_model": "legacy",
            },
        ),
        (OcrRequest, {"config_id": 1, "image_base64": "abc", "configSource": "USER"}),
    ],
)
def test_exact_llm_requests_forbid_legacy_identity_and_override_fields(model, payload):
    with pytest.raises(ValidationError) as exc:
        model.model_validate(payload)
    assert exc.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.asyncio
async def test_resolve_provider_maps_exact_error_without_fallback(monkeypatch):
    captured = {}

    async def _raise(**kwargs):
        captured.update(kwargs)
        raise LLMConfigNotFoundError(456)

    monkeypatch.setattr("src.api.routes.llm.aresolve_model", _raise)
    with pytest.raises(HTTPException) as exc:
        await _resolve_provider(
            db=AsyncMock(), user_id="123", capability="EMBEDDING", config_id=456
        )
    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "LLM_CONFIG_NOT_FOUND"
    assert captured["user_id"] == 123
    assert captured["config_id"] == 456
    assert captured["capability"] == "EMBEDDING"
    assert "config_source" not in captured
    assert "override_model" not in captured


@pytest.mark.asyncio
async def test_ocr_endpoint_resolves_vision_by_exact_config_id(monkeypatch):
    captured = {}
    provider = AsyncMock()
    provider.analyze_image.return_value = SimpleNamespace(
        model_dump=lambda: {"content": "text"}
    )

    async def _resolve(db, user_id, capability, *, config_id):
        captured.update(
            {"user_id": user_id, "capability": capability, "config_id": config_id}
        )
        return provider

    monkeypatch.setattr("src.api.routes.llm._resolve_provider", _resolve)
    response = await extract_text_from_image(
        OcrRequest(config_id=77, image_base64="abc", prompt="read text"),
        x_user_id="123",
        db=AsyncMock(),
    )

    assert response.code == 200
    assert captured == {"user_id": "123", "capability": "VISION", "config_id": 77}
    provider.analyze_image.assert_awaited_once_with(
        image_base64="abc", prompt="read text", media_type="image/jpeg"
    )
