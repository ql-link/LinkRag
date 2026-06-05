# -*- coding: utf-8 -*-
"""/llm 路由边界 ID 归一：user_id / config_id 字符串 → int，非法值 → 422。

锁定 M2/M3 修复：弱类型 ID 不再下沉到 SQL 靠驱动隐式转换，路由层显式校验。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.routes.llm import _coerce_int


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
