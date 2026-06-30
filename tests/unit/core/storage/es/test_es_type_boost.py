"""ES BM25 chunk_type 类型加权查询结构测试（不需真实 ES）。

只断言 ``EsBm25Retriever._build_query`` 生成的 DSL 结构正确：ES 端类型加权
按 BM25_TYPE_BOOST 对命中 chunk 固定加分、不影响过滤命中集。
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.core.storage.es.retrieval import EsBm25Retriever
from src.core.storage.es.retrieval_models import Bm25RecallRequest

pytestmark = pytest.mark.unit


def test_build_query_emits_constant_score_per_type(monkeypatch):
    monkeypatch.setattr(settings, "BM25_TYPE_BOOST", {"heading": 3.0, "table": 1.5})
    request = Bm25RecallRequest(user_id=1, dataset_id=9, tokens=["x"], top_k=10)

    query = EsBm25Retriever._build_query(request, ["x"])

    boosts = {
        clause["constant_score"]["filter"]["term"]["chunk_type"]: clause["constant_score"][
            "boost"
        ]
        for clause in query["bool"]["should"]
    }
    assert boosts == {"heading": 3.0, "table": 1.5}
    # 主查询与过滤不受影响：must 仍是 multi_match，filter 仍含租户约束
    assert query["bool"]["must"][0]["multi_match"]["fields"] == [
        "coarse_tokens^2",
        "fine_tokens",
    ]
    assert {"term": {"user_id": 1}} in query["bool"]["filter"]


def test_build_query_no_should_when_boost_empty(monkeypatch):
    monkeypatch.setattr(settings, "BM25_TYPE_BOOST", {})
    request = Bm25RecallRequest(user_id=1, dataset_id=9, tokens=["x"], top_k=10)

    query = EsBm25Retriever._build_query(request, ["x"])

    assert "should" not in query["bool"]
