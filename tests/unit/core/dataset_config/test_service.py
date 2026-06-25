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

import math
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


@pytest.mark.asyncio
async def test_recall_new_fields_default_from_settings(monkeypatch):
    """无配置行 → 三项新字段取运行期系统默认（enabled_sources 由逗号串解析为 list）。"""
    from src.config import settings

    monkeypatch.setattr(settings, "RECALL_ENABLED_SOURCES", "bm25,sparse,dense")
    monkeypatch.setattr(settings, "RECALL_FUSION_STRATEGY", "weighted_score")
    monkeypatch.setattr(settings, "RECALL_FUSION_BM25_WEIGHT", 0.2)
    monkeypatch.setattr(settings, "RECALL_FUSION_SPARSE_WEIGHT", 0.3)
    monkeypatch.setattr(settings, "RECALL_FUSION_DENSE_WEIGHT", 0.5)
    monkeypatch.setattr(settings, "RERANK_DEFAULT_TOP_N", 8)
    monkeypatch.setattr(settings, "RECALL_STRICT_DEFAULT", False)

    db = _fake_db(row=None)
    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert bundle.recall.recall_enabled_sources == ["bm25", "sparse", "dense"]
    assert bundle.recall.recall_fusion_strategy == "weighted_score"
    assert bundle.recall.fusion_bm25_weight == 0.2
    assert bundle.recall.fusion_sparse_weight == 0.3
    assert bundle.recall.fusion_dense_weight == 0.5
    assert bundle.recall.rerank_top_n == 8
    assert bundle.recall.recall_strict is False


@pytest.mark.asyncio
async def test_recall_new_fields_dataset_override():
    """数据集 JSON 覆盖召回 source、fusion、rerank 与 strict 字段。"""
    db = _fake_db(
        row=_row(
            recall={
                "recall_enabled_sources": ["bm25", "sparse"],
                "recall_fusion_strategy": "weighted_score",
                "fusion_bm25_weight": 0.1,
                "fusion_sparse_weight": 0.2,
                "fusion_dense_weight": 0.7,
                "rerank_top_n": 3,
                "recall_strict": True,
            }
        )
    )
    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert bundle.recall.recall_enabled_sources == ["bm25", "sparse"]
    assert bundle.recall.recall_fusion_strategy == "weighted_score"
    assert bundle.recall.fusion_bm25_weight == 0.1
    assert bundle.recall.fusion_sparse_weight == 0.2
    assert bundle.recall.fusion_dense_weight == 0.7
    assert bundle.recall.rerank_top_n == 3
    assert bundle.recall.recall_strict is True


@pytest.mark.asyncio
async def test_recall_new_fields_l1_fallback(monkeypatch):
    """运维改系统级 RECALL_ENABLED_SOURCES / RERANK_DEFAULT_TOP_N / RECALL_STRICT_DEFAULT
    → 无配置数据集跟随。"""
    from src.config import settings

    monkeypatch.setattr(settings, "RECALL_ENABLED_SOURCES", "bm25,sparse")
    monkeypatch.setattr(settings, "RECALL_FUSION_STRATEGY", "rrf")
    monkeypatch.setattr(settings, "RECALL_FUSION_BM25_WEIGHT", 0.4)
    monkeypatch.setattr(settings, "RECALL_FUSION_SPARSE_WEIGHT", 0.6)
    monkeypatch.setattr(settings, "RECALL_FUSION_DENSE_WEIGHT", 0.0)
    monkeypatch.setattr(settings, "RERANK_DEFAULT_TOP_N", 5)
    monkeypatch.setattr(settings, "RECALL_STRICT_DEFAULT", True)

    db = _fake_db(row=None)
    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert bundle.recall.recall_enabled_sources == ["bm25", "sparse"]
    assert bundle.recall.recall_fusion_strategy == "rrf"
    assert bundle.recall.fusion_bm25_weight == 0.4
    assert bundle.recall.fusion_sparse_weight == 0.6
    assert bundle.recall.fusion_dense_weight == 0.0
    assert bundle.recall.rerank_top_n == 5
    assert bundle.recall.recall_strict is True


@pytest.mark.asyncio
async def test_recall_rerank_top_n_non_positive_propagates():
    """JSON 里 rerank_top_n <= 0 → ValidationError 向上传播（不静默降级）。"""
    db = _fake_db(row=_row(recall={"rerank_top_n": 0}))
    with pytest.raises(ValidationError) as exc_info:
        await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert "rerank_top_n" in str(exc_info.value)


@pytest.mark.asyncio
async def test_recall_fusion_invalid_dataset_config_propagates():
    """dataset recall_config 中 fusion 配置非法 → ValidationError 向上传播。"""
    db = _fake_db(row=_row(recall={"recall_fusion_strategy": "unknown"}))
    with pytest.raises(ValidationError) as exc_info:
        await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert "recall_fusion_strategy" in str(exc_info.value)

    db = _fake_db(row=_row(recall={"fusion_dense_weight": math.inf}))
    with pytest.raises(ValidationError) as exc_info:
        await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert "fusion_dense_weight" in str(exc_info.value)
