# -*- coding: utf-8 -*-
"""/llm 路由边界行为：user_id / config_id 归一（M2/M3）+ 缺配置 → 422。

锁定 M2/M3 修复：弱类型 ID 不再下沉到 SQL 靠驱动隐式转换，路由层显式校验；
并验证直调 LLM 缺用户模型配置时翻成 HTTP 422，不走系统模型兜底。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.api.routes.llm import OcrRequest, _coerce_int, _resolve_provider, extract_text_from_image
from src.core.llm.exceptions import UserModelConfigMissingError


def test_coerce_int_valid():
    assert _coerce_int("123", "X-User-Id") == 123


def test_coerce_int_rejects_non_numeric():
    with pytest.raises(HTTPException) as exc:
        _coerce_int("abc", "X-User-Id")
    assert exc.value.status_code == 422
    assert "X-User-Id" in exc.value.detail


def test_coerce_int_rejects_empty():
    with pytest.raises(HTTPException) as exc:
        _coerce_int("", "config_id")
    assert exc.value.status_code == 422
    assert "config_id" in exc.value.detail


@pytest.mark.asyncio
async def test_resolve_provider_missing_config_maps_to_clear_422(monkeypatch):
    """统一解析未命中抛 UserModelConfigMissingError → HTTP 422，返回可读缺配置原因。"""

    async def _raise(**kwargs):
        raise UserModelConfigMissingError("EMBEDDING", 123)

    monkeypatch.setattr("src.api.routes.llm.aresolve_user_model", _raise)
    with pytest.raises(HTTPException) as exc:
        await _resolve_provider(db=AsyncMock(), user_id="123", capability="EMBEDDING")
    assert exc.value.status_code == 422
    assert exc.value.detail == {
        "code": "LLM_CONFIG_MISSING",
        "message": (
            "user LLM config missing for capability EMBEDDING; "
            "please configure the model before calling this API"
        ),
        "capability": "EMBEDDING",
        "user_id": 123,
    }


@pytest.mark.asyncio
async def test_resolve_provider_disables_system_fallback(monkeypatch):
    captured = {}
    provider = object()

    async def _resolve(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(provider=provider)

    monkeypatch.setattr("src.api.routes.llm.aresolve_user_model", _resolve)

    resolved = await _resolve_provider(
        db=AsyncMock(),
        user_id="123",
        capability="CHAT",
        config_id="456",
        override_model="gpt-test",
    )

    assert resolved is provider
    assert captured["user_id"] == 123
    assert captured["capability"] == "CHAT"
    assert captured["config_id"] == 456
    assert captured["config_source"] == "USER"
    assert captured["allow_system_fallback"] is False
    assert captured["override_model"] == "gpt-test"


@pytest.mark.asyncio
async def test_legacy_ocr_endpoint_resolves_vision_capability(monkeypatch):
    captured = {}
    provider = AsyncMock()
    provider.analyze_image.return_value = SimpleNamespace(model_dump=lambda: {"content": "text"})

    async def _resolve(
        db, user_id, capability, *, config_id=None, config_source=None, override_model=None
    ):
        captured.update(
            {
                "user_id": user_id,
                "capability": capability,
                "config_id": config_id,
                "config_source": config_source,
                "override_model": override_model,
            }
        )
        return provider

    monkeypatch.setattr("src.api.routes.llm._resolve_provider", _resolve)

    response = await extract_text_from_image(
        OcrRequest(config_id="77", image_base64="abc", prompt="read text"),
        x_user_id="123",
        db=AsyncMock(),
    )

    assert response.code == 200
    assert captured == {
        "user_id": "123",
        "capability": "VISION",
        "config_id": "77",
        "config_source": "USER",
        "override_model": None,
    }
    # OCR 统一走 VISION：调 analyze_image，prompt 透传、media_type 由 base64 嗅探（"abc" 无法解码 → 回退 jpeg）
    provider.analyze_image.assert_awaited_once_with(
        image_base64="abc", prompt="read text", media_type="image/jpeg"
    )
