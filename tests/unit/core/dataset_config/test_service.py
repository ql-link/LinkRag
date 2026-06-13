# -*- coding: utf-8 -*-
"""DatasetConfigService 只读取数据集配置的单元测试（LINK-148）。

覆盖验收契约中映射到配置读取/合并的场景：
- 数据集有配置记录 → 数据集级值生效；
- 数据集无配置记录 → 全部系统默认（不写库）；
- 部分覆盖 → 未覆盖字段取系统默认；
- DB 故障 → 降级系统默认、不抛、不阻断；
- JSON 字段类型非法 → ValidationError 向上传播（不静默降级），错误含字段名。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from src.core.dataset_config import DatasetConfigService


def _fake_db(*, row=None, raises=None):
    """构造假 AsyncSession：execute() 返回的 result.scalar_one_or_none() 给 row，或 execute 抛错。"""
    db = MagicMock(name="AsyncSession")
    if raises is not None:
        db.execute = AsyncMock(side_effect=raises)
    else:
        result = MagicMock(name="Result")
        result.scalar_one_or_none.return_value = row
        db.execute = AsyncMock(return_value=result)
    return db


def _row(**json_cols):
    """构造带四个 JSON 列的假 ORM 行；未给的列用空 dict（全取默认）。"""
    row = MagicMock(name="DatasetParseConfig")
    row.chunking_config = json_cols.get("chunking", {})
    row.enhancement_config = json_cols.get("enhancement", {})
    row.pdf_config = json_cols.get("pdf", {})
    row.recall_config = json_cols.get("recall", {})
    return row


@pytest.mark.asyncio
async def test_no_row_returns_system_defaults_without_write():
    db = _fake_db(row=None)
    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert bundle.chunking.overlap_tokens == 64
    assert bundle.recall.recall_result_limit == 20
    # 增强配置只剩开关（不再有 table_model / vision_model），默认取系统开关。
    assert bundle.enhancement.enable_table_enhancement is True
    assert bundle.enhancement.enable_image_enhancement is True
    assert not hasattr(bundle.enhancement, "table_model")
    # 只读：绝不写库。
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_row_present_applies_dataset_values():
    db = _fake_db(
        row=_row(
            chunking={"overlap_tokens": 32},
            recall={"recall_result_limit": 10, "dense_score_threshold": 0.5},
        )
    )
    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert bundle.chunking.overlap_tokens == 32
    assert bundle.recall.recall_result_limit == 10
    assert bundle.recall.dense_score_threshold == 0.5


@pytest.mark.asyncio
async def test_partial_override_fills_unset_from_defaults():
    db = _fake_db(row=_row(chunking={"heading_break_level": 2}))
    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert bundle.chunking.heading_break_level == 2  # 覆盖字段
    assert bundle.chunking.overlap_tokens == 64  # 未覆盖 → 系统默认
    assert bundle.chunking.min_candidate_chunk_tokens == 128


@pytest.mark.asyncio
async def test_enhancement_legacy_model_keys_ignored():
    """历史 JSON 仍含 table_model / vision_model → 被忽略，开关照常生效（向后兼容）。"""
    db = _fake_db(
        row=_row(
            enhancement={
                "enable_table_enhancement": False,
                "enable_image_enhancement": True,
                "table_model": "qwen-max",
                "vision_model": "qwen-vl",
            }
        )
    )
    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert bundle.enhancement.enable_table_enhancement is False  # 覆盖字段生效
    assert bundle.enhancement.enable_image_enhancement is True
    assert not hasattr(bundle.enhancement, "table_model")  # 旧模型字段被忽略
    assert not hasattr(bundle.enhancement, "vision_model")


@pytest.mark.asyncio
async def test_db_failure_degrades_to_defaults():
    db = _fake_db(raises=RuntimeError("db down"))
    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    # 不抛、回退系统默认。
    assert bundle.chunking.overlap_tokens == 64
    assert bundle.recall.recall_result_limit == 20


@pytest.mark.asyncio
async def test_invalid_json_field_type_propagates_with_field_name():
    db = _fake_db(row=_row(chunking={"overlap_tokens": "invalid"}))
    with pytest.raises(ValidationError) as exc_info:
        await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert "overlap_tokens" in str(exc_info.value)


@pytest.mark.asyncio
async def test_system_settings_are_l1_fallback(monkeypatch):
    """运维改了系统级默认 → 无配置数据集跟随生效（不是被静态默认锁死）。"""
    from src.config import settings

    monkeypatch.setattr(settings, "CHUNKING_OVERLAP_TOKENS", 16)
    monkeypatch.setattr(settings, "RECALL_RESULT_LIMIT", 33)

    db = _fake_db(row=None)
    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert bundle.chunking.overlap_tokens == 16
    assert bundle.recall.recall_result_limit == 33
