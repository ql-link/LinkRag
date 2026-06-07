# -*- coding: utf-8 -*-
"""/llm 路由边界行为：user_id / config_id 归一（M2/M3）+ 缺配置 → 404。

锁定 M2/M3 修复：弱类型 ID 不再下沉到 SQL 靠驱动隐式转换，路由层显式校验；
并验证统一解析未命中（含系统兜底）时翻成 HTTP 404，保持原有对外契约。
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.api.routes.llm import _coerce_int, _resolve_provider
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
