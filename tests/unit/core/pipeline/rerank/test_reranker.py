"""按 Dataset 使用独立 reranker，并回填原 fusion slot。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.pipeline.recall.models import RecallHit
from src.core.pipeline.rerank import PostRecallReranker, RerankRequest


class _Provider:
    def __init__(self, scores, *, error=None):
        self.scores = scores
        self.error = error
        self.calls = []

    async def rerank(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            results=[SimpleNamespace(index=index, score=score) for index, score in self.scores],
            usage=None,
        )


def _hit(chunk_id: str, dataset_id: int, fused_score: float) -> RecallHit:
    return RecallHit(
        chunk_id=chunk_id,
        doc_id=dataset_id * 10,
        dataset_id=dataset_id,
        fused_score=fused_score,
        scores={"dense": fused_score},
    )


def _context(provider, config_id: int, *, enabled: bool = True):
    resolved = SimpleNamespace(
        provider=provider,
        model_name=f"reranker-{config_id}",
        provider_type="test",
        config_id=config_id,
    )
    return SimpleNamespace(
        config=SimpleNamespace(recall=SimpleNamespace(enable_rerank=enabled)),
        rerank=resolved if enabled else None,
    )


async def test_multiple_dataset_rerankers_only_reorder_their_own_fusion_slots(monkeypatch):
    monkeypatch.setattr(
        "src.core.pipeline.rerank.reranker.report_usage_nowait", lambda **_kwargs: None
    )
    hits = [
        _hit("d1-a", 1, 0.9),
        _hit("d2-a", 2, 0.8),
        _hit("d1-b", 1, 0.7),
        _hit("d2-b", 2, 0.6),
    ]
    provider_1 = _Provider([(0, 0.1), (1, 0.9)])
    provider_2 = _Provider([(0, 0.2), (1, 0.8)])
    contents = {hit.chunk_id: f"body::{hit.chunk_id}" for hit in hits}

    response = await PostRecallReranker().rerank(
        RerankRequest(
            query="q",
            user_id=7,
            hits=hits,
            contents=contents,
            dataset_contexts={
                1: _context(provider_1, 101),
                2: _context(provider_2, 201),
            },
        )
    )

    assert [hit.chunk_id for hit in response.hits] == ["d1-b", "d2-b", "d1-a", "d2-a"]
    assert response.rerank_applied is True
    assert provider_1.calls[0]["documents"] == ["body::d1-a", "body::d1-b"]
    assert provider_1.calls[0]["model"] == "reranker-101"
    assert provider_2.calls[0]["documents"] == ["body::d2-a", "body::d2-b"]
    assert provider_2.calls[0]["model"] == "reranker-201"


async def test_disabled_dataset_keeps_its_slots_while_other_dataset_reranks(monkeypatch):
    monkeypatch.setattr(
        "src.core.pipeline.rerank.reranker.report_usage_nowait", lambda **_kwargs: None
    )
    hits = [
        _hit("d1-a", 1, 0.9),
        _hit("d2-a", 2, 0.8),
        _hit("d1-b", 1, 0.7),
        _hit("d2-b", 2, 0.6),
    ]
    provider = _Provider([(0, 0.1), (1, 0.9)])
    response = await PostRecallReranker().rerank(
        RerankRequest(
            query="q",
            user_id=7,
            hits=hits,
            contents={hit.chunk_id: hit.chunk_id for hit in hits},
            dataset_contexts={
                1: _context(None, 101, enabled=False),
                2: _context(provider, 201),
            },
        )
    )
    assert [hit.chunk_id for hit in response.hits] == ["d1-a", "d2-b", "d1-b", "d2-a"]


async def test_provider_failure_degrades_only_that_dataset(monkeypatch):
    monkeypatch.setattr(
        "src.core.pipeline.rerank.reranker.report_usage_nowait", lambda **_kwargs: None
    )
    hits = [_hit("a", 1, 0.9), _hit("b", 1, 0.8)]
    response = await PostRecallReranker().rerank(
        RerankRequest(
            query="q",
            user_id=7,
            hits=hits,
            contents={"a": "a", "b": "b"},
            dataset_contexts={1: _context(_Provider([], error=RuntimeError("down")), 101)},
        )
    )
    assert [hit.chunk_id for hit in response.hits] == ["a", "b"]
    assert response.rerank_applied is False
    assert all(hit.rerank_score is None for hit in response.hits)


async def test_missing_dataset_context_fails_before_provider_call():
    with pytest.raises(ValueError, match="execution context is required"):
        await PostRecallReranker().rerank(
            RerankRequest(
                query="q",
                user_id=7,
                hits=[_hit("a", 1, 0.9)],
                contents={"a": "a"},
                dataset_contexts={},
            )
        )


@pytest.mark.parametrize("top_n", [0, -1])
async def test_invalid_top_n_fails_before_fetch(top_n):
    called = []

    async def _fetch(*_args):
        called.append(True)
        return {}

    with pytest.raises(ValueError, match="top_n"):
        await PostRecallReranker(content_fetcher=_fetch).rerank(
            RerankRequest(query="q", user_id=7, hits=[_hit("a", 1, 0.9)], top_n=top_n)
        )
    assert called == []
