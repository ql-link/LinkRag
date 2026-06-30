"""Bm25SparseEncoder 单元测试：coarse+fine 双段 BM25-TF 权重 + 维度映射的纯逻辑验证。"""

from __future__ import annotations

import pytest

from src.core.storage.qdrant_bm25.encoder import (
    _PERSON_FINE,
    Bm25SparseEncoder,
    term_to_dimension,
)


def _enc(**overrides) -> Bm25SparseEncoder:
    base = dict(k1=1.2, b=0.75, avgdl_coarse=5.0, avgdl_fine=5.0, coarse_boost=2.0)
    base.update(overrides)
    return Bm25SparseEncoder(**base)


def _coarse_dim(term: str) -> int:
    return term_to_dimension(term)  # 默认 coarse 段


def _fine_dim(term: str) -> int:
    return term_to_dimension(term, person=_PERSON_FINE)


def _val(vector, dim: int) -> float:
    return dict(zip(vector.indices, vector.values))[dim]


def test_term_to_dimension_stable_and_in_uint32() -> None:
    assert term_to_dimension("退费") == term_to_dimension("退费")  # 确定性
    assert 0 <= term_to_dimension("退费") < 2**32  # 满 uint32 区间
    assert term_to_dimension("退费") != term_to_dimension("查询")  # 不同词不同维度


def test_coarse_fine_spaces_isolated() -> None:
    """同一个词在 coarse 段与 fine 段落到不同维度（person 盐隔离），两路 IDF 才能独立。"""
    assert _coarse_dim("退费") != _fine_dim("退费")


def test_encode_document_fills_both_spaces() -> None:
    """文档侧：coarse 词进 coarse 段、fine 词进 fine 段，互不串段。"""
    doc = _enc().encode_document(["退费"], ["退费", "查询"])
    dims = set(doc.indices)
    assert _coarse_dim("退费") in dims  # coarse 段
    assert _fine_dim("退费") in dims and _fine_dim("查询") in dims  # fine 段
    assert _coarse_dim("查询") not in dims  # fine 的"查询"不该落进 coarse 段


def test_encode_query_lights_both_spaces_with_boost() -> None:
    """查询侧：每个 coarse 词同时点亮 coarse 段(value=coarse_boost)与 fine 段(value=1)。"""
    q = _enc(coarse_boost=2.0).encode_query(["退费", "退费", "查询"])  # 含重复
    assert len(q.indices) == 4  # 2 个唯一词 × 2 段
    assert _val(q, _coarse_dim("退费")) == 2.0  # coarse 段带 boost
    assert _val(q, _fine_dim("退费")) == 1.0  # fine 段 ×1
    assert set(q.values) == {2.0, 1.0}


def test_document_query_share_dimension_per_space() -> None:
    """精准匹配根基：同词在文档侧与查询侧的 coarse / fine 段各自映射到同一维度。"""
    enc = _enc()
    doc = enc.encode_document(["退费", "流程"], ["退费", "流"])
    query = enc.encode_query(["退费"])
    # coarse 路：query coarse 词命中文档 coarse 段
    assert _coarse_dim("退费") in doc.indices and _coarse_dim("退费") in query.indices
    # fine 路：query 同一个 coarse 词命中文档 fine 段（嵌在长词里被细分出的子词那一路）
    assert _fine_dim("退费") in doc.indices and _fine_dim("退费") in query.indices


def test_tf_saturation() -> None:
    """词频饱和：同长度下 tf=3 的权重 < 3 × tf=1（区别于 TF-IDF 的线性）。coarse 段验证。"""
    enc = _enc(avgdl_coarse=4.0)
    w3 = _val(enc.encode_document(["退费", "退费", "退费", "x"], ["_"]), _coarse_dim("退费"))
    w1 = _val(enc.encode_document(["退费", "a", "b", "c"], ["_"]), _coarse_dim("退费"))
    assert w3 < 3 * w1


def test_length_normalization() -> None:
    """长度归一：同 tf 下，短文档的词权重 > 长文档。coarse 段验证。"""
    enc = _enc(avgdl_coarse=5.0)
    short = _val(enc.encode_document(["退费", "x"], ["_"]), _coarse_dim("退费"))
    long = _val(enc.encode_document(["退费", *["x"] * 9], ["_"]), _coarse_dim("退费"))
    assert short > long


def test_coarse_fine_use_separate_avgdl() -> None:
    """coarse 段用 avgdl_coarse、fine 段用 avgdl_fine 各自归一，互不影响。"""
    # 同一份 token：coarse 段 dl=4 远超 avgdl_coarse=2（重罚）；fine 段 dl=4 等 avgdl_fine=4（轻罚）。
    doc = _enc(avgdl_coarse=2.0, avgdl_fine=4.0).encode_document(
        ["退费", "a", "b", "c"], ["退费", "a", "b", "c"]
    )
    assert _val(doc, _fine_dim("退费")) > _val(doc, _coarse_dim("退费"))


def test_known_value_matches_smoke() -> None:
    """复现 smoke：avgdl_coarse=25/6、退费 tf=3、dl=4 → coarse 段权重 ≈1.585。"""
    w = _val(
        _enc(avgdl_coarse=25 / 6).encode_document("退费 退费 退费 流程".split(), ["_"]),
        _coarse_dim("退费"),
    )
    assert abs(w - 1.585) < 0.01


def test_empty_document_returns_empty_vector() -> None:
    enc = _enc()
    assert enc.encode_document([], []).indices == []
    assert enc.encode_document(["", "   "], ["  "]).indices == []  # 全空白也算空


def test_empty_query_returns_empty_vector() -> None:
    enc = _enc()
    assert enc.encode_query([]).indices == []
    assert enc.encode_query(["", "  "]).indices == []


def test_invalid_params_rejected() -> None:
    with pytest.raises(ValueError):
        _enc(avgdl_coarse=0)  # avgdl 必须为正
    with pytest.raises(ValueError):
        _enc(avgdl_fine=0)
    with pytest.raises(ValueError):
        _enc(b=1.5)  # b ∈ [0,1]
    with pytest.raises(ValueError):
        _enc(k1=-1.0)  # k1 ≥ 0
    with pytest.raises(ValueError):
        _enc(coarse_boost=-0.1)  # coarse_boost ≥ 0
