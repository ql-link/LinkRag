# -*- coding: utf-8 -*-
"""/llm 路由边界行为：user_id / config_id 归一（M2/M3）+ 缺配置 → 404。

锁定 M2/M3 修复：弱类型 ID 不再下沉到 SQL 靠驱动隐式转换，路由层显式校验；
并验证统一解析未命中（含系统兜底）时翻成 HTTP 404，保持原有对外契约。
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
async def test_resolve_provider_missing_config_maps_to_404(monkeypatch):
    """统一解析未命中（含系统兜底）抛 UserModelConfigMissingError → HTTP 404，
    保持 /llm 端点原有对外行为。"""
    async def _raise(**kwargs):
        raise UserModelConfigMissingError("EMBEDDING", 123)

    monkeypatch.setattr("src.api.routes.llm.aresolve_user_model", _raise)
    with pytest.raises(HTTPException) as exc:
        await _resolve_provider(db=AsyncMock(), user_id="123", capability="EMBEDDING")
    assert exc.value.status_code == 404
    assert "EMBEDDING" in exc.value.detail


@pytest.mark.asyncio
async def test_legacy_ocr_endpoint_resolves_vision_capability(monkeypatch):
    captured = {}
    provider = AsyncMock()
    provider.extract_text.return_value = SimpleNamespace(model_dump=lambda: {"content": "text"})

    async def _resolve(db, user_id, capability, *, config_id=None, override_model=None):
        captured.update(
            {
                "user_id": user_id,
                "capability": capability,
                "config_id": config_id,
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
        "override_model": None,
    }
    provider.extract_text.assert_awaited_once_with(image_base64="abc", prompt="read text")
