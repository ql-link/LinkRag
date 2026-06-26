"""Bm25SparseEncoder 单元测试：路 A 的 BM25-TF 权重 + 维度映射的纯逻辑验证。"""

from __future__ import annotations

import pytest

from src.core.storage.qdrant_bm25.encoder import (
    Bm25SparseEncoder,
    term_to_dimension,
)


def _weight(vector, term: str) -> float:
    return dict(zip(vector.indices, vector.values))[term_to_dimension(term)]


def test_term_to_dimension_stable_and_in_uint32() -> None:
    assert term_to_dimension("退费") == term_to_dimension("退费")  # 确定性
    assert 0 <= term_to_dimension("退费") < 2**32  # 满 uint32 区间
    assert term_to_dimension("退费") != term_to_dimension("查询")  # 不同词不同维度


def test_encode_query_values_all_one_and_dedup() -> None:
    enc = Bm25SparseEncoder(k1=1.2, b=0.75, avgdl=5.0)
    v = enc.encode_query(["退费", "查询", "退费"])  # 含重复
    assert set(v.values) == {1.0}  # 查询侧每维 value=1（IDF 服务端补）
    assert len(v.indices) == 2  # 去重


def test_document_and_query_share_dimension() -> None:
    """精准匹配的根基：同一个词在文档侧与查询侧映射到同一维度。"""
    enc = Bm25SparseEncoder(k1=1.2, b=0.75, avgdl=5.0)
    doc = enc.encode_document(["退费", "流程"])
    query = enc.encode_query(["退费"])
    dim = term_to_dimension("退费")
    assert dim in doc.indices and dim in query.indices


def test_tf_saturation() -> None:
    """词频饱和：同长度下，tf=3 的权重 < 3 × tf=1（区别于 TF-IDF 的线性）。"""
    enc = Bm25SparseEncoder(k1=1.2, b=0.75, avgdl=4.0)
    w3 = _weight(enc.encode_document(["退费", "退费", "退费", "x"]), "退费")  # dl=4, tf=3
    w1 = _weight(enc.encode_document(["退费", "a", "b", "c"]), "退费")  # dl=4, tf=1
    assert w3 < 3 * w1


def test_length_normalization() -> None:
    """长度归一：同 tf 下，短文档的词权重 > 长文档。"""
    enc = Bm25SparseEncoder(k1=1.2, b=0.75, avgdl=5.0)
    short = _weight(enc.encode_document(["退费", "x"]), "退费")  # dl=2
    long = _weight(enc.encode_document(["退费", *["x"] * 9]), "退费")  # dl=10
    assert short > long


def test_known_value_matches_smoke() -> None:
    """复现 smoke：avgdl=25/6、退费 tf=3、dl=4 → 权重 ≈1.585。"""
    enc = Bm25SparseEncoder(k1=1.2, b=0.75, avgdl=25 / 6)
    w = _weight(enc.encode_document("退费 退费 退费 流程".split()), "退费")
    assert abs(w - 1.585) < 0.01


def test_empty_document_returns_empty_vector() -> None:
    enc = Bm25SparseEncoder(k1=1.2, b=0.75, avgdl=5.0)
    assert enc.encode_document([]).indices == []
    assert enc.encode_document(["", "   "]).indices == []  # 全空白也算空


def test_invalid_params_rejected() -> None:
    with pytest.raises(ValueError):
        Bm25SparseEncoder(k1=1.2, b=0.75, avgdl=0)  # avgdl 必须为正
    with pytest.raises(ValueError):
        Bm25SparseEncoder(k1=1.2, b=1.5, avgdl=5.0)  # b ∈ [0,1]
    with pytest.raises(ValueError):
        Bm25SparseEncoder(k1=-1.0, b=0.75, avgdl=5.0)  # k1 ≥ 0
