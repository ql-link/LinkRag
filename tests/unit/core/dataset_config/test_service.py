# -*- coding: utf-8 -*-
"""DatasetConfigService 只读取数据集配置的单元测试（LINK-148）。

覆盖验收契约中映射到配置读取/合并的场景：
- 数据集有配置记录 → 数据集级值生效；
- 数据集无配置记录 → 全部系统默认（不写库）；
- 空 enhancement_config → 所有增强关闭；非空部分覆盖 → 未覆盖字段取系统默认；
- DB 故障 → 降级系统默认、不抛、不阻断；
- JSON 字段类型非法 → ValidationError 向上传播（不静默降级），错误含字段名。
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from src.core.dataset_config import DatasetConfigService


def _set_link_136_recall_defaults(monkeypatch):
    """固定本 issue 关心的系统级默认，避免本地 .env 覆盖影响单测。"""
    from src.config import settings

    monkeypatch.setattr(settings, "RECALL_RESULT_LIMIT", 64)
    monkeypatch.setattr(settings, "RECALL_BM25_TOP_K", 100)
    monkeypatch.setattr(settings, "RECALL_SPARSE_TOP_K", 50)
    monkeypatch.setattr(settings, "RECALL_DENSE_TOP_K", 100)


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
    """构造带四个 JSON 列的假 ORM 行；空 enhancement dict 表示所有增强关闭。"""
    row = MagicMock(name="DatasetParseConfig")
    row.chunking_config = json_cols.get("chunking", {})
    row.enhancement_config = json_cols.get("enhancement", {})
    row.pdf_config = json_cols.get("pdf", {})
    row.recall_config = json_cols.get("recall", {})
    row.sparse_embedding_config_id = None
    row.dense_embedding_config_id = None
    row.sparse_embedding_config_source = "USER"
    row.dense_embedding_config_source = "USER"
    return row


@pytest.mark.asyncio
async def test_no_row_returns_system_defaults_without_write(monkeypatch):
    _set_link_136_recall_defaults(monkeypatch)
    db = _fake_db(row=None)
    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert bundle.chunking.overlap_tokens == 64
    assert bundle.recall.recall_result_limit == 64
    assert bundle.recall.bm25_top_k == 100
    assert bundle.recall.sparse_top_k == 50
    assert bundle.recall.dense_top_k == 100
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
async def test_empty_enhancement_config_disables_all_enhancement(monkeypatch):
    """Java 默认写入 {} 时，不应继承 Settings=true 意外开启增强。"""
    from src.config import settings

    monkeypatch.setattr(settings, "MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT", True)
    monkeypatch.setattr(settings, "MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT", True)
    monkeypatch.setattr(settings, "MARKDOWN_PARSER_ENABLE_HEADING_HIERARCHY", True)

    bundle = await DatasetConfigService().get_config(
        user_id=1,
        dataset_id=2,
        db=_fake_db(row=_row(enhancement={})),
    )

    assert bundle.enhancement.enable_table_enhancement is False
    assert bundle.enhancement.enable_image_enhancement is False
    assert bundle.enhancement.enable_heading_hierarchy is False


@pytest.mark.asyncio
async def test_non_empty_enhancement_config_keeps_partial_settings_fallback(monkeypatch):
    """非空部分覆盖保持原契约，未提供的开关继续继承 Settings。"""
    from src.config import settings

    monkeypatch.setattr(settings, "MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT", True)
    monkeypatch.setattr(settings, "MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT", True)

    bundle = await DatasetConfigService().get_config(
        user_id=1,
        dataset_id=2,
        db=_fake_db(row=_row(enhancement={"enable_image_enhancement": False})),
    )

    assert bundle.enhancement.enable_table_enhancement is True
    assert bundle.enhancement.enable_image_enhancement is False


@pytest.mark.asyncio
async def test_row_present_applies_vector_model_binding_source():
    row = _row()
    row.sparse_embedding_config_id = 11
    row.sparse_embedding_config_source = "SYSTEM"
    row.dense_embedding_config_id = 12
    row.dense_embedding_config_source = "USER"
    db = _fake_db(row=row)

    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert bundle.vector_models.sparse_embedding_config_id == 11
    assert bundle.vector_models.sparse_embedding_config_source == "SYSTEM"
    assert bundle.vector_models.dense_embedding_config_id == 12
    assert bundle.vector_models.dense_embedding_config_source == "USER"


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
async def test_db_failure_degrades_to_defaults(monkeypatch):
    _set_link_136_recall_defaults(monkeypatch)
    db = _fake_db(raises=RuntimeError("db down"))
    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    # 不抛、回退系统默认。
    assert bundle.chunking.overlap_tokens == 64
    assert bundle.recall.recall_result_limit == 64


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
    monkeypatch.setattr(settings, "RECALL_BM25_TOP_K", 88)
    monkeypatch.setattr(settings, "RECALL_SPARSE_TOP_K", 77)
    monkeypatch.setattr(settings, "RECALL_DENSE_TOP_K", 66)

    db = _fake_db(row=None)
    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert bundle.chunking.overlap_tokens == 16
    assert bundle.recall.recall_result_limit == 33
    assert bundle.recall.bm25_top_k == 88
    assert bundle.recall.sparse_top_k == 77
    assert bundle.recall.dense_top_k == 66


@pytest.mark.asyncio
async def test_recall_route_top_k_defaults_do_not_use_facade_defaults(monkeypatch):
    """pipeline 专用 top_k 只读 RECALL_*；facade 直调默认值不应污染 RecallConfig。"""
    from src.config import settings

    monkeypatch.setattr(settings, "RECALL_DENSE_TOP_K", 100)
    monkeypatch.setattr(settings, "RECALL_SPARSE_TOP_K", 50)
    monkeypatch.setattr(settings, "RECALL_BM25_TOP_K", 100)
    monkeypatch.setattr(settings, "DENSE_RETRIEVAL_TOP_K", 10)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_TOP_K", 10)

    db = _fake_db(row=None)
    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert bundle.recall.dense_top_k == 100
    assert bundle.recall.sparse_top_k == 50
    assert bundle.recall.bm25_top_k == 100


@pytest.mark.asyncio
async def test_recall_new_fields_default_from_settings(monkeypatch):
    """无配置行 → 新字段取运行期系统默认（enabled_sources 由逗号串解析为 list）。"""
    from src.config import settings

    monkeypatch.setattr(settings, "RECALL_ENABLED_SOURCES", "bm25,sparse,dense")
    monkeypatch.setattr(settings, "RECALL_BM25_TOP_K", 101)
    monkeypatch.setattr(settings, "RECALL_SPARSE_TOP_K", 51)
    monkeypatch.setattr(settings, "RECALL_DENSE_TOP_K", 99)
    monkeypatch.setattr(settings, "RECALL_FUSION_STRATEGY", "weighted_score")
    monkeypatch.setattr(settings, "RECALL_RRF_K", 60)
    monkeypatch.setattr(settings, "RECALL_FUSION_BM25_WEIGHT", 0.2)
    monkeypatch.setattr(settings, "RECALL_FUSION_SPARSE_WEIGHT", 0.3)
    monkeypatch.setattr(settings, "RECALL_FUSION_DENSE_WEIGHT", 0.5)
    monkeypatch.setattr(settings, "RERANK_DEFAULT_TOP_N", 8)
    monkeypatch.setattr(settings, "RECALL_STRICT_DEFAULT", False)

    db = _fake_db(row=None)
    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert bundle.recall.recall_enabled_sources == ["bm25", "sparse", "dense"]
    assert bundle.recall.bm25_top_k == 101
    assert bundle.recall.sparse_top_k == 51
    assert bundle.recall.dense_top_k == 99
    assert bundle.recall.recall_fusion_strategy == "weighted_score"
    assert bundle.recall.rrf_k == 60
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
                "bm25_top_k": 60,
                "sparse_top_k": 40,
                "dense_top_k": 70,
                "recall_enabled_sources": ["bm25", "sparse"],
                "recall_fusion_strategy": "weighted_score",
                "rrf_k": 10,
                "fusion_bm25_weight": 0.1,
                "fusion_sparse_weight": 0.2,
                "fusion_dense_weight": 0.7,
                "rerank_top_n": 3,
                "recall_strict": True,
            }
        )
    )
    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert bundle.recall.bm25_top_k == 60
    assert bundle.recall.sparse_top_k == 40
    assert bundle.recall.dense_top_k == 70
    assert bundle.recall.recall_enabled_sources == ["bm25", "sparse"]
    assert bundle.recall.recall_fusion_strategy == "weighted_score"
    assert bundle.recall.rrf_k == 10
    assert bundle.recall.fusion_bm25_weight == 0.1
    assert bundle.recall.fusion_sparse_weight == 0.2
    assert bundle.recall.fusion_dense_weight == 0.7
    assert bundle.recall.rerank_top_n == 3
    assert bundle.recall.recall_strict is True


@pytest.mark.asyncio
async def test_recall_legacy_json_missing_bm25_top_k_falls_back_to_settings(monkeypatch):
    """旧 JSON 已写字段保持原值；新增 bm25_top_k 未写时回退系统默认。"""
    from src.config import settings

    monkeypatch.setattr(settings, "RECALL_BM25_TOP_K", 100)
    db = _fake_db(
        row=_row(
            recall={
                "recall_result_limit": 20,
                "dense_top_k": 10,
                "sparse_top_k": 10,
            }
        )
    )

    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert bundle.recall.recall_result_limit == 20
    assert bundle.recall.dense_top_k == 10
    assert bundle.recall.sparse_top_k == 10
    assert bundle.recall.bm25_top_k == 100


@pytest.mark.asyncio
async def test_recall_new_fields_l1_fallback(monkeypatch):
    """运维改系统级 RECALL_ENABLED_SOURCES / RERANK_DEFAULT_TOP_N / RECALL_STRICT_DEFAULT
    → 无配置数据集跟随。"""
    from src.config import settings

    monkeypatch.setattr(settings, "RECALL_ENABLED_SOURCES", "bm25,sparse")
    monkeypatch.setattr(settings, "RECALL_FUSION_STRATEGY", "rrf")
    monkeypatch.setattr(settings, "RECALL_RRF_K", 10)
    monkeypatch.setattr(settings, "RECALL_FUSION_BM25_WEIGHT", 0.4)
    monkeypatch.setattr(settings, "RECALL_FUSION_SPARSE_WEIGHT", 0.6)
    monkeypatch.setattr(settings, "RECALL_FUSION_DENSE_WEIGHT", 0.0)
    monkeypatch.setattr(settings, "RERANK_DEFAULT_TOP_N", 5)
    monkeypatch.setattr(settings, "RECALL_STRICT_DEFAULT", True)

    db = _fake_db(row=None)
    bundle = await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert bundle.recall.recall_enabled_sources == ["bm25", "sparse"]
    assert bundle.recall.recall_fusion_strategy == "rrf"
    assert bundle.recall.rrf_k == 10
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

    db = _fake_db(row=_row(recall={"rrf_k": 0}))
    with pytest.raises(ValidationError) as exc_info:
        await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert "rrf_k" in str(exc_info.value)


@pytest.mark.parametrize(
    "field", ["recall_result_limit", "bm25_top_k", "sparse_top_k", "dense_top_k"]
)
@pytest.mark.asyncio
async def test_recall_top_k_non_positive_propagates(field: str):
    """JSON 里召回 top_k/候选池窗口 <= 0 → ValidationError 向上传播，错误含字段名。"""
    db = _fake_db(row=_row(recall={field: 0}))
    with pytest.raises(ValidationError) as exc_info:
        await DatasetConfigService().get_config(user_id=1, dataset_id=2, db=db)

    assert field in str(exc_info.value)
