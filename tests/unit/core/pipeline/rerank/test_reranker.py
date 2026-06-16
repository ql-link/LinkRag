"""``PostRecallReranker.rerank`` 单测，对齐 acceptance.feature 全部 15 Scenario。

依赖以替身注入，不连真实 DB / LLM：
- ``content_fetcher``：按预置正文 dict 返回；可记录调用以断言「未访问 DB」。
- ``model_resolver``：返回带 fake provider 的 ResolvedModel；可抛异常模拟未配置。
- fake provider.rerank：返回预置 (index, score) 或抛异常模拟调用失败。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.llm.exceptions import UserModelConfigMissingError
from src.core.pipeline.recall.models import RecallHit
from src.core.pipeline.rerank import PostRecallReranker, RerankRequest


# ---- 替身 ----

class FakeProvider:
    """记录 rerank 调用入参；按预置返回或抛异常。"""

    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.calls: list[dict] = []

    async def rerank(self, query, documents, model=None, top_n=None):
        self.calls.append(
            {"query": query, "documents": list(documents), "model": model, "top_n": top_n}
        )
        if self._error is not None:
            raise self._error
        return self._result


def fake_rerank_result(pairs):
    """pairs: list[(index, score)] -> 形如 RerankResult 的轻量对象。"""
    items = [SimpleNamespace(index=i, score=s) for i, s in pairs]
    return SimpleNamespace(results=items)


def make_fetcher(contents, spy=None):
    async def _fetch(chunk_ids, user_id):
        if spy is not None:
            spy.append((list(chunk_ids), user_id))
        return {cid: contents[cid] for cid in chunk_ids if cid in contents}
    return _fetch


def make_resolver(provider=None, model_name="rerank-m", error=None, spy=None):
    async def _resolve(**kwargs):
        if spy is not None:
            spy.append(kwargs)
        if error is not None:
            raise error
        return SimpleNamespace(provider=provider, model_name=model_name)
    return _resolve


def _hit(cid, fused):
    return RecallHit(chunk_id=cid, doc_id=10, dataset_id=1, fused_score=fused, scores={"dense": fused})


# ==== 主流程 ====

async def test_main_flow_fillback_then_rerank_then_sorted():
    hits = [_hit(f"c{i}", 1.0 - i * 0.1) for i in range(1, 6)]  # c1..c5 降序
    contents = {f"c{i}": f"正文{i}" for i in range(1, 6)}
    provider = FakeProvider(result=fake_rerank_result([(0, 0.2), (1, 0.9), (2, 0.5), (3, 0.1), (4, 0.7)]))
    reranker = PostRecallReranker(
        content_fetcher=make_fetcher(contents),
        model_resolver=make_resolver(provider=provider),
    )

    resp = await reranker.rerank(RerankRequest(query="数据治理流程", user_id=10002, hits=hits))

    # 按 RRF 顺序构造 documents，调用一次，query 透传
    assert len(provider.calls) == 1
    assert provider.calls[0]["query"] == "数据治理流程"
    assert provider.calls[0]["documents"] == ["正文1", "正文2", "正文3", "正文4", "正文5"]
    # 按 rerank_score 降序：c2(.9) c5(.7) c3(.5) c1(.2) c4(.1)
    assert [h.chunk_id for h in resp.hits] == ["c2", "c5", "c3", "c1", "c4"]
    assert resp.rerank_applied is True
    # 保留原字段 + 新增 rerank 字段，rank 从 1 连续
    assert [h.rerank_rank for h in resp.hits] == [1, 2, 3, 4, 5]
    assert resp.hits[0].rerank_score == 0.9
    assert resp.hits[0].fused_score == hits[1].fused_score
    assert resp.hits[0].scores == hits[1].scores


async def test_order_determined_by_rerank_not_rrf():
    hits = [_hit("c1", 0.9), _hit("c2", 0.8), _hit("c3", 0.7)]
    provider = FakeProvider(result=fake_rerank_result([(0, 0.3), (1, 0.2), (2, 0.9)]))
    reranker = PostRecallReranker(
        content_fetcher=make_fetcher({"c1": "a", "c2": "b", "c3": "c"}),
        model_resolver=make_resolver(provider=provider),
    )

    resp = await reranker.rerank(RerankRequest(query="q", user_id=1, hits=hits))

    assert [h.chunk_id for h in resp.hits] == ["c3", "c1", "c2"]
    assert resp.hits[0].chunk_id == "c3"
    assert resp.hits[0].rerank_rank == 1
    # fused_score / scores 维持原 RRF 取值
    for h in resp.hits:
        original = next(x for x in hits if x.chunk_id == h.chunk_id)
        assert h.fused_score == original.fused_score
        assert h.scores == original.scores


# ==== top_n 入参与截断 ====

async def test_default_top_n_is_8(monkeypatch):
    hits = [_hit(f"c{i}", 1.0 - i * 0.01) for i in range(12)]
    contents = {f"c{i}": f"t{i}" for i in range(12)}
    # 分数与下标同序递减，重排后顺序 == 输入顺序，便于断言取前 8
    provider = FakeProvider(result=fake_rerank_result([(i, 1.0 - i * 0.01) for i in range(12)]))
    reranker = PostRecallReranker(
        content_fetcher=make_fetcher(contents),
        model_resolver=make_resolver(provider=provider),
    )

    resp = await reranker.rerank(RerankRequest(query="q", user_id=1, hits=hits))  # 不传 top_n

    assert len(resp.hits) == 8
    assert [h.chunk_id for h in resp.hits] == [f"c{i}" for i in range(8)]


@pytest.mark.parametrize("bad_top_n", [0, -1])
async def test_non_positive_top_n_rejected(bad_top_n):
    resolve_spy: list = []
    provider = FakeProvider(result=fake_rerank_result([(0, 0.9)]))
    reranker = PostRecallReranker(
        content_fetcher=make_fetcher({"c1": "a", "c2": "b", "c3": "c"}),
        model_resolver=make_resolver(provider=provider, spy=resolve_spy),
    )

    with pytest.raises(ValueError):
        await reranker.rerank(
            RerankRequest(query="q", user_id=10002,
                          hits=[_hit("c1", 0.9), _hit("c2", 0.8), _hit("c3", 0.7)],
                          top_n=bad_top_n)
        )
    # 入参校验在最前，未触达正文回填 / 模型解析 / rerank 调用
    assert resolve_spy == []
    assert provider.calls == []


@pytest.mark.parametrize(
    "n_content, top_n, expected",
    [(20, 8, 8), (5, 8, 5), (8, 8, 8), (10, 3, 3)],
)
async def test_top_n_truncation(n_content, top_n, expected):
    hits = [_hit(f"c{i}", 1.0 - i * 0.001) for i in range(n_content)]
    contents = {f"c{i}": f"t{i}" for i in range(n_content)}
    provider = FakeProvider(result=fake_rerank_result([(i, 1.0 - i * 0.001) for i in range(n_content)]))
    reranker = PostRecallReranker(
        content_fetcher=make_fetcher(contents),
        model_resolver=make_resolver(provider=provider),
    )

    resp = await reranker.rerank(RerankRequest(query="q", user_id=1, hits=hits, top_n=top_n))

    assert len(resp.hits) == expected


# ==== 正文回填与过滤 ====

async def test_only_hits_with_content_participate():
    # 模拟 DB 过滤后仅 c1 有正文（c2 非 ACTIVE / c3 空 / c4 他人，均不在回填结果）
    hits = [_hit("c1", 0.9), _hit("c2", 0.8), _hit("c3", 0.7), _hit("c4", 0.6)]
    provider = FakeProvider(result=fake_rerank_result([(0, 0.5)]))
    reranker = PostRecallReranker(
        content_fetcher=make_fetcher({"c1": "正文1"}),
        model_resolver=make_resolver(provider=provider),
    )

    resp = await reranker.rerank(RerankRequest(query="q", user_id=10002, hits=hits))

    assert provider.calls[0]["documents"] == ["正文1"]
    assert [h.chunk_id for h in resp.hits] == ["c1"]


async def test_partial_missing_content_only_scores_present_ones():
    hits = [_hit(f"c{i}", 1.0 - i * 0.1) for i in range(1, 6)]  # c1..c5
    provider = FakeProvider(result=fake_rerank_result([(0, 0.9), (1, 0.8), (2, 0.7)]))
    reranker = PostRecallReranker(
        content_fetcher=make_fetcher({"c1": "a", "c3": "c", "c5": "e"}),  # c2/c4 缺正文
        model_resolver=make_resolver(provider=provider),
    )

    resp = await reranker.rerank(RerankRequest(query="q", user_id=1, hits=hits))

    assert provider.calls[0]["documents"] == ["a", "c", "e"]
    ids = [h.chunk_id for h in resp.hits]
    assert "c2" not in ids and "c4" not in ids
    assert set(ids) == {"c1", "c3", "c5"}
    # 返回结构不带任何剔除计数字段
    assert not hasattr(resp, "skipped_no_content")


# ==== 空输入与全部缺正文 ====

async def test_empty_hits_short_circuits_without_db_or_model():
    fetch_spy: list = []
    resolve_spy: list = []
    reranker = PostRecallReranker(
        content_fetcher=make_fetcher({}, spy=fetch_spy),
        model_resolver=make_resolver(provider=FakeProvider(), spy=resolve_spy),
    )

    resp = await reranker.rerank(RerankRequest(query="q", user_id=1, hits=[]))

    assert resp.hits == []
    assert resp.rerank_applied is False
    assert fetch_spy == []      # 未访问 DB
    assert resolve_spy == []    # 未解析模型


async def test_all_missing_content_returns_empty_without_model():
    resolve_spy: list = []
    provider = FakeProvider()
    reranker = PostRecallReranker(
        content_fetcher=make_fetcher({}),  # 全部查不到正文
        model_resolver=make_resolver(provider=provider, spy=resolve_spy),
    )

    resp = await reranker.rerank(
        RerankRequest(query="q", user_id=1, hits=[_hit("c1", 0.9), _hit("c2", 0.8), _hit("c3", 0.7)])
    )

    assert resp.hits == []
    assert resp.rerank_applied is False
    assert resolve_spy == []     # 未解析模型
    assert provider.calls == []  # 未调用 rerank


# ==== 失败与降级语义 ====

async def test_missing_rerank_config_hard_fails_without_degrade():
    hits = [_hit("c1", 0.9), _hit("c2", 0.8), _hit("c3", 0.7)]
    reranker = PostRecallReranker(
        content_fetcher=make_fetcher({"c1": "a", "c2": "b", "c3": "c"}),
        model_resolver=make_resolver(error=UserModelConfigMissingError("RERANK", 10002)),
    )

    with pytest.raises(UserModelConfigMissingError):
        await reranker.rerank(RerankRequest(query="q", user_id=10002, hits=hits))


async def test_rerank_call_error_degrades_to_rrf_order():
    hits = [_hit("c1", 0.9), _hit("c2", 0.8), _hit("c3", 0.7), _hit("c4", 0.6)]
    provider = FakeProvider(error=RuntimeError("rerank service 5xx"))
    reranker = PostRecallReranker(
        content_fetcher=make_fetcher({"c1": "a", "c2": "b", "c3": "c", "c4": "d"}),
        model_resolver=make_resolver(provider=provider),
    )

    resp = await reranker.rerank(RerankRequest(query="q", user_id=1, hits=hits))

    assert [h.chunk_id for h in resp.hits] == ["c1", "c2", "c3", "c4"]  # RRF 顺序
    assert resp.rerank_applied is False
    assert all(h.rerank_score is None and h.rerank_rank is None for h in resp.hits)


@pytest.mark.parametrize(
    "indices, applied, scored_ids, tail_ids",
    [
        ([(0, 0.9), (1, 0.8), (2, 0.7)], True, ["c1", "c2", "c3"], []),     # 正常
        ([(0, 0.9), (5, 0.8), (2, 0.7)], True, ["c1", "c3"], ["c2"]),       # 过滤越界 5
        ([(0, 0.9), (0, 0.8), (1, 0.7)], True, ["c1", "c2"], ["c3"]),       # 去重重复 0
        ([], False, [], []),                                               # 空 -> 降级
    ],
)
async def test_unreliable_index_mapping(indices, applied, scored_ids, tail_ids):
    hits = [_hit("c1", 0.9), _hit("c2", 0.8), _hit("c3", 0.7)]
    provider = FakeProvider(result=fake_rerank_result(indices))
    reranker = PostRecallReranker(
        content_fetcher=make_fetcher({"c1": "a", "c2": "b", "c3": "c"}),
        model_resolver=make_resolver(provider=provider),
    )

    resp = await reranker.rerank(RerankRequest(query="q", user_id=1, hits=hits))

    assert resp.rerank_applied is applied
    if not applied:
        # 降级：RRF 顺序，rerank 字段全空
        assert [h.chunk_id for h in resp.hits] == ["c1", "c2", "c3"]
        assert all(h.rerank_score is None for h in resp.hits)
        return
    # 合法 index 对应候选有 rerank_score
    by_id = {h.chunk_id: h for h in resp.hits}
    for cid in scored_ids:
        assert by_id[cid].rerank_score is not None
    # 未返回的有正文候选入无分 tail
    for cid in tail_ids:
        assert by_id[cid].rerank_score is None


# ==== rerank 模型来源 ====

async def test_uses_user_configured_model_no_system_fallback():
    resolve_spy: list = []
    provider = FakeProvider(result=fake_rerank_result([(0, 0.9)]))
    reranker = PostRecallReranker(
        content_fetcher=make_fetcher({"c1": "a"}),
        model_resolver=make_resolver(provider=provider, model_name="user-rerank", spy=resolve_spy),
    )

    await reranker.rerank(RerankRequest(query="q", user_id=10002, hits=[_hit("c1", 0.9)]))

    assert resolve_spy[0]["capability"] == "RERANK"
    assert resolve_spy[0]["allow_system_fallback"] is False
    assert resolve_spy[0]["user_id"] == 10002
    # rerank 调用使用解析出的用户模型名
    assert provider.calls[0]["model"] == "user-rerank"
