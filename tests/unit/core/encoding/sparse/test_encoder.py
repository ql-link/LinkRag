"""normalize_lexical_weights 清洗规则单测。

本地 BGE-M3 编码器已随系统级稀疏路径移除；运行时清洗逻辑（min_weight 过滤、top_k 截断、
index 升序、空向量报错）由 :func:`normalize_lexical_weights` 承载，被 per-user adapter 路径
（:class:`AdapterSparseVectorEncoder`）复用，故在此直接对该函数钉住行为。
"""

from __future__ import annotations

import pytest

from src.core.encoding.sparse.encoder import normalize_lexical_weights
from src.core.encoding.sparse.exceptions import (
    SparseVectorEncodingError,
    SparseVectorOutputError,
)


def test_should_merge_and_sort_indices_ascending():
    # token_id 可能是字符串或整数，权重原样保留；输出按 index 升序。
    vector = normalize_lexical_weights({"7": 0.2, "3": 0.4, 11: 1.5, "2": 0.1}, top_k=0)

    assert vector.indices == [2, 3, 7, 11]
    assert vector.values == [0.1, 0.4, 0.2, 1.5]


def test_should_apply_top_k_by_weight_then_return_indices_sorted():
    vector = normalize_lexical_weights({1: 0.1, 2: 0.9, 3: 0.8, 4: 0.7}, top_k=2)

    # 先按权重取 top_k（2、3），再按 index 升序输出。
    assert vector.indices == [2, 3]
    assert vector.values == [0.9, 0.8]


def test_should_filter_min_weight_and_empty_output_fails():
    with pytest.raises(SparseVectorOutputError):
        normalize_lexical_weights({1: 0.05, 2: 0.1}, min_weight=0.2)


def test_should_keep_max_weight_for_duplicate_index():
    # 同一 token 因上游格式差异重复出现时，保留最大权重，避免重复维度写入 Qdrant。
    vector = normalize_lexical_weights({"5": 0.3, 5: 0.8}, top_k=0)

    assert vector.indices == [5]
    assert vector.values == [0.8]


def test_should_fail_when_item_is_not_mapping():
    with pytest.raises(SparseVectorEncodingError):
        normalize_lexical_weights([(1, 0.5)])


def test_should_fail_when_lexical_weight_item_is_invalid():
    with pytest.raises(SparseVectorEncodingError):
        normalize_lexical_weights({object(): "bad"})


def test_should_fail_when_index_is_negative():
    with pytest.raises(SparseVectorEncodingError):
        normalize_lexical_weights({-1: 0.5})
