"""入参校验 Scenario：query 非法 / 空 dataset_ids 允许 / doc_ids 透传。"""

import pytest

from src.core.pipeline.recall import (
    SOURCE_BM25,
    SOURCE_DENSE,
    SOURCE_SPARSE,
    RecallPipeline,
    RecallRequest,
    RecallValidationError,
    RetrieverHit,
)
from tests.unit.core.pipeline.recall.conftest import FakeRetriever


def _hit(chunk_id, source, score=1.0, doc_id=100, dataset_id=10):
    return RetrieverHit(
        chunk_id=chunk_id,
        doc_id=doc_id,
        dataset_id=dataset_id,
        score=score,
        source=source,
    )


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
@pytest.mark.asyncio
async def test_invalid_query_raises(query: str):
    """查询文本非法时抛参数错误（Outline 3 例）。三路均未被触发。"""
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[])
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[])
    pipeline = RecallPipeline([dense, sparse, bm25])

    with pytest.raises(RecallValidationError):
        await pipeline.execute(RecallRequest(user_id=1, query=query, dataset_ids=[10]))

    assert dense.calls == []
    assert sparse.calls == []
    assert bm25.calls == []


@pytest.mark.asyncio
async def test_empty_dataset_ids_allowed():
    """数据集范围为空表示全库召回，pipeline 接受不抛错。"""
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("c1", SOURCE_DENSE)])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[])
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[])
    pipeline = RecallPipeline([dense, sparse, bm25])

    response = await pipeline.execute(RecallRequest(user_id=1, query="任意查询", dataset_ids=[]))

    for r in (dense, sparse, bm25):
        assert r.calls == [("任意查询", [], None)]
    assert {h.chunk_id for h in response.hits} == {"c1"}


@pytest.mark.parametrize("field", ["top_k", "bm25_top_k", "sparse_top_k", "dense_top_k"])
@pytest.mark.asyncio
async def test_non_positive_fusion_limit_or_route_top_k_raises(field: str):
    """融合候选池窗口与三路执行期 top_k 均必须为正，错误信息包含字段名。"""
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[])
    pipeline = RecallPipeline([bm25])
    kwargs = {
        "user_id": 1,
        "query": "任意查询",
        "dataset_ids": [10],
        "top_k": 64,
        "bm25_top_k": 100,
        "sparse_top_k": 50,
        "dense_top_k": 100,
    }
    kwargs[field] = 0

    with pytest.raises(RecallValidationError) as exc_info:
        await pipeline.execute(RecallRequest(**kwargs))

    assert field in str(exc_info.value)


@pytest.mark.asyncio
async def test_doc_ids_pass_through():
    """同时传 dataset_ids 与 doc_ids 时透传到各路。"""
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[])
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[])
    pipeline = RecallPipeline([dense, sparse, bm25])

    await pipeline.execute(
        RecallRequest(user_id=1, query="任意查询", dataset_ids=[10, 11], doc_ids=[2001])
    )

    for r in (dense, sparse, bm25):
        assert r.calls == [("任意查询", [10, 11], [2001])]
