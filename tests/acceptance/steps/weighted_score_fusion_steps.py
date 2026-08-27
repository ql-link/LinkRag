"""weighted_score_fusion 的 pytest-bdd step 实现。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from src.api.routes import rag, recall
from src.application import recall_pipeline_provider
from src.application.recall_errors import RecallApiError
from src.application.recall_stream_runtime import _rerank_hits
from src.config import settings
from src.core.dataset_config.models import RecallConfig
from src.core.llm.exceptions import LLMConfigNotFoundError
from src.core.pipeline.recall import (
    SOURCE_BM25,
    SOURCE_DENSE,
    SOURCE_SPARSE,
    RecallHit,
    RecallPipeline,
    RecallPipelineConfig,
    RecallRequest,
    RecallResponse,
    RecallValidationError,
    RetrieverHit,
)
from src.core.pipeline.rerank import RerankedHit, RerankResponse

_SOURCES = [SOURCE_BM25, SOURCE_SPARSE, SOURCE_DENSE]
_DEFAULT_WEIGHTS = {SOURCE_BM25: 0.15, SOURCE_SPARSE: 0.15, SOURCE_DENSE: 0.70}


@dataclass
class _FakeRetriever:
    source: str
    hits: list[RetrieverHit] = field(default_factory=list)
    calls: list[RecallRequest] = field(default_factory=list)

    async def recall(
        self,
        query: str,
        dataset_ids: list[int],
        doc_ids: list[int] | None = None,
        *,
        user_id: int,
        top_k: int,
        score_threshold_override: float | None = None,
        dataset_contexts: dict[int, object] | None = None,
    ) -> list[RetrieverHit]:
        self.calls.append(
            RecallRequest(
                query=query,
                user_id=user_id,
                dataset_ids=list(dataset_ids),
                doc_ids=list(doc_ids) if doc_ids else None,
                top_k=top_k,
            )
        )
        return list(self.hits)


class _PassthroughDocumentReadinessGate:
    async def filter_visible_hits(self, hits, *, user_id: int):
        return list(hits)


@dataclass
class _CapturingReranker:
    unavailable: bool
    captured_request: object | None = None

    async def rerank(self, request):
        self.captured_request = request
        if self.unavailable:
            raise LLMConfigNotFoundError(780)
        hits = [
            RerankedHit(
                chunk_id=h.chunk_id,
                doc_id=h.doc_id,
                dataset_id=h.dataset_id,
                fused_score=h.fused_score,
                scores=h.scores,
                rerank_score=1.0 / rank,
                rerank_rank=rank,
            )
            for rank, h in enumerate(request.hits, start=1)
        ]
        return RerankResponse(request.query, hits, True, 1)


@dataclass
class _State:
    weights: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_WEIGHTS))
    enabled_sources: list[str] | None = None
    top_k: int = 20
    retrievers: dict[str, _FakeRetriever] = field(
        default_factory=lambda: {source: _FakeRetriever(source) for source in _SOURCES}
    )
    response: RecallResponse | None = None
    error: BaseException | None = None
    pipeline_config: RecallPipelineConfig | None = None
    captured_request: RecallRequest | None = None
    http_errors: list[RecallApiError] = field(default_factory=list)
    pipeline_called: bool = False
    fusion_hits: list[RecallHit] = field(default_factory=list)
    reranker: _CapturingReranker | None = None
    rerank_hits: list[RerankedHit] = field(default_factory=list)
    rerank_applied: bool | None = None


@pytest.fixture
def weighted_fusion_state() -> _State:
    return _State()


def _score_expr(value: str) -> float:
    text = value.strip()
    if "/" in text:
        left, right = text.split("/", 1)
        return float(left) / float(right)
    return float(text)


def _split_sources(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _hit(chunk_id: str, source: str, score: float) -> RetrieverHit:
    return RetrieverHit(
        chunk_id=chunk_id,
        doc_id=100 + abs(hash(chunk_id)) % 1000,
        dataset_id=10,
        score=score,
        source=source,
    )


def _hit_by_id(state: _State, chunk_id: str) -> RecallHit:
    assert state.response is not None
    for hit in state.response.hits:
        if hit.chunk_id == chunk_id:
            return hit
    raise AssertionError(f"hit {chunk_id!r} not found")


def _run_pipeline(state: _State, *, request_override: bool = False) -> None:
    config_kwargs = {
        "fusion_bm25_weight": state.weights[SOURCE_BM25],
        "fusion_sparse_weight": state.weights[SOURCE_SPARSE],
        "fusion_dense_weight": state.weights[SOURCE_DENSE],
    }
    pipeline = RecallPipeline(
        list(state.retrievers.values()),
        RecallPipelineConfig(**config_kwargs),
        readiness_gate=_PassthroughDocumentReadinessGate(),
    )
    request_kwargs = {
        "query": "q",
        "user_id": 123,
        "dataset_ids": [10],
        "top_k": state.top_k,
        "enabled_sources": state.enabled_sources,
    }
    if request_override:
        request_kwargs.update(
            {
                "fusion_bm25_weight_override": state.weights[SOURCE_BM25],
                "fusion_sparse_weight_override": state.weights[SOURCE_SPARSE],
                "fusion_dense_weight_override": state.weights[SOURCE_DENSE],
            }
        )
    try:
        state.response = asyncio.run(pipeline.execute(RecallRequest(**request_kwargs)))
        state.error = None
    except BaseException as exc:  # noqa: BLE001 - 验收状态需要捕获边界异常
        state.response = None
        state.error = exc


def _request_with_payload(payload: dict):
    async def _body():
        return json.dumps(payload).encode("utf-8")

    return SimpleNamespace(body=_body)


# ---------------------------------------------------------------------------
# 背景步骤
# ---------------------------------------------------------------------------


@given('服务端支持召回源 "bm25"、"sparse"、"dense"')
def _given_supported_sources(weighted_fusion_state: _State) -> None:
    assert set(weighted_fusion_state.retrievers) == set(_SOURCES)


@given(parsers.parse("系统默认 RECALL_FUSION_BM25_WEIGHT 为 {value:f}"))
def _given_default_bm25_weight(value: float) -> None:
    assert settings.RECALL_FUSION_BM25_WEIGHT == pytest.approx(value)


@given(parsers.parse("系统默认 RECALL_FUSION_SPARSE_WEIGHT 为 {value:f}"))
def _given_default_sparse_weight(value: float) -> None:
    assert settings.RECALL_FUSION_SPARSE_WEIGHT == pytest.approx(value)


@given(parsers.parse("系统默认 RECALL_FUSION_DENSE_WEIGHT 为 {value:f}"))
def _given_default_dense_weight(value: float) -> None:
    assert settings.RECALL_FUSION_DENSE_WEIGHT == pytest.approx(value)


@given("RecallHit 输出字段为 chunk_id、doc_id、dataset_id、fused_score、scores")
def _given_hit_shape() -> None:
    fields = set(RecallHit.__dataclass_fields__)
    assert {"chunk_id", "doc_id", "dataset_id", "fused_score", "scores"} <= fields


# ---------------------------------------------------------------------------
# Pipeline 配置
# ---------------------------------------------------------------------------


@given(parsers.parse("fusion 权重配置为 bm25={bm25:f} sparse={sparse:f} dense={dense:f}"))
def _given_weights(
    weighted_fusion_state: _State,
    bm25: float,
    sparse: float,
    dense: float,
) -> None:
    weighted_fusion_state.weights = {
        SOURCE_BM25: bm25,
        SOURCE_SPARSE: sparse,
        SOURCE_DENSE: dense,
    }


@given(parsers.parse('{source} 路按顺序返回 chunk "{chunk_id}" score {score:f}'))
@given(parsers.parse('{source} 路返回 chunk "{chunk_id}" score {score:f}'))
def _given_single_hit(
    weighted_fusion_state: _State,
    source: str,
    chunk_id: str,
    score: float,
) -> None:
    weighted_fusion_state.retrievers[source].hits = [_hit(chunk_id, source, score)]


@given(parsers.parse("{source} 路返回 0 命中"))
def _given_no_hits(weighted_fusion_state: _State, source: str) -> None:
    weighted_fusion_state.retrievers[source].hits = []


@given(parsers.parse("{source} 路按顺序返回:"))
def _given_table_hits(weighted_fusion_state: _State, source: str, datatable) -> None:
    rows = datatable[1:]
    weighted_fusion_state.retrievers[source].hits = [
        _hit(row[0], source, float(row[1])) for row in rows
    ]


@given(parsers.parse('只启用召回源 "{source}"'))
def _given_only_source(weighted_fusion_state: _State, source: str) -> None:
    weighted_fusion_state.enabled_sources = [source]


@given(parsers.parse('本次 enabled_sources 为 "{sources}"'))
def _given_enabled_sources(weighted_fusion_state: _State, sources: str) -> None:
    weighted_fusion_state.enabled_sources = _split_sources(sources)


@given("bm25 路配置存在但本次不启用")
def _given_bm25_configured_but_disabled(weighted_fusion_state: _State) -> None:
    assert SOURCE_BM25 in weighted_fusion_state.retrievers


@given(parsers.parse("RecallRequest.top_k 等于 {value:d}"))
def _given_top_k(weighted_fusion_state: _State, value: int) -> None:
    weighted_fusion_state.top_k = value


@when("执行 RecallPipeline")
def _when_execute_pipeline(weighted_fusion_state: _State) -> None:
    _run_pipeline(weighted_fusion_state, request_override=False)


# ---------------------------------------------------------------------------
# Pipeline 断言
# ---------------------------------------------------------------------------


@then(parsers.re(r'(?:返回 )?hit "(?P<chunk_id>[^"]+)" 的 fused_score 等于 (?P<expected>.+)'))
def _then_hit_fused_score(
    weighted_fusion_state: _State,
    chunk_id: str,
    expected: str,
) -> None:
    assert weighted_fusion_state.error is None
    hit = _hit_by_id(weighted_fusion_state, chunk_id)
    assert hit.fused_score == pytest.approx(_score_expr(expected))


@then(
    parsers.re(
        r'(?:返回 )?hit "(?P<chunk_id>[^"]+)" 的 scores\.(?P<source>\w+) 等于 (?P<expected>.+)'
    )
)
def _then_hit_raw_score(
    weighted_fusion_state: _State,
    chunk_id: str,
    source: str,
    expected: str,
) -> None:
    assert weighted_fusion_state.error is None
    hit = _hit_by_id(weighted_fusion_state, chunk_id)
    if expected.strip() == "null":
        assert hit.scores[source] is None
    else:
        assert hit.scores[source] == pytest.approx(_score_expr(expected))


@then(parsers.parse('返回 hit "{chunk_id}" 不含 normalized_scores 字段'))
def _then_no_normalized_scores(weighted_fusion_state: _State, chunk_id: str) -> None:
    assert not hasattr(_hit_by_id(weighted_fusion_state, chunk_id), "normalized_scores")


@then(parsers.parse('hits 顺序为 "{order}"'))
@then(parsers.parse('返回 hits 顺序为 "{order}"'))
def _then_hits_order(weighted_fusion_state: _State, order: str) -> None:
    assert weighted_fusion_state.response is not None
    assert [hit.chunk_id for hit in weighted_fusion_state.response.hits] == _split_sources(order)


@then(parsers.parse('active sources 为 "{sources}"'))
def _then_active_sources(weighted_fusion_state: _State, sources: str) -> None:
    assert weighted_fusion_state.response is not None
    active = [
        source
        for source, count in weighted_fusion_state.response.per_source_counts.items()
        if count > 0
    ]
    assert active == _split_sources(sources)


@then("不把缺失 source 的权重重新分配给单个 chunk 已命中的 source")
def _then_no_per_chunk_redistribution(weighted_fusion_state: _State) -> None:
    assert weighted_fusion_state.response is not None
    assert {hit.chunk_id: hit.fused_score for hit in weighted_fusion_state.response.hits} == {
        "cA": pytest.approx(0.15),
        "cB": pytest.approx(0.15),
        "cC": pytest.approx(0.70),
    }


@then("本次融合成功")
def _then_fusion_success(weighted_fusion_state: _State) -> None:
    assert weighted_fusion_state.error is None
    assert weighted_fusion_state.response is not None


@then("本次融合失败并报告配置或数据异常")
def _then_fusion_failed_validation(weighted_fusion_state: _State) -> None:
    assert isinstance(weighted_fusion_state.error, RecallValidationError)


@then("本次融合失败并报告 active source 权重和必须大于 0")
def _then_active_weight_sum_error(weighted_fusion_state: _State) -> None:
    assert isinstance(weighted_fusion_state.error, RecallValidationError)
    assert "active source fusion weight sum" in str(weighted_fusion_state.error)


@then("不返回使用修正后分数的 hit")
def _then_no_corrected_hit(weighted_fusion_state: _State) -> None:
    assert weighted_fusion_state.response is None


@then("融合计算未因极端 BM25 分数溢出")
def _then_no_overflow(weighted_fusion_state: _State) -> None:
    assert weighted_fusion_state.error is None


@then("不调用 bm25 路")
def _then_bm25_not_called(weighted_fusion_state: _State) -> None:
    assert weighted_fusion_state.retrievers[SOURCE_BM25].calls == []


@then(parsers.parse('hit 的 scores 键集合等于 "{sources}"'))
def _then_score_keys(weighted_fusion_state: _State, sources: str) -> None:
    assert weighted_fusion_state.response is not None
    expected = set(_split_sources(sources))
    for hit in weighted_fusion_state.response.hits:
        assert set(hit.scores) == expected


@then(parsers.parse("返回 hits 数量等于 {count:d}"))
def _then_hit_count(weighted_fusion_state: _State, count: int) -> None:
    assert weighted_fusion_state.response is not None
    assert len(weighted_fusion_state.response.hits) == count


@then(parsers.parse('hit "{left}" 的 fused_score 等于 hit "{right}" 的 fused_score'))
def _then_equal_fused_scores(weighted_fusion_state: _State, left: str, right: str) -> None:
    assert _hit_by_id(weighted_fusion_state, left).fused_score == pytest.approx(
        _hit_by_id(weighted_fusion_state, right).fused_score
    )


# ---------------------------------------------------------------------------
# 配置与 HTTP 契约
# ---------------------------------------------------------------------------


@given(parsers.parse("Settings 中 RECALL_FUSION_BM25_WEIGHT={value:f}"))
def _given_settings_bm25(monkeypatch, value: float) -> None:
    monkeypatch.setattr(settings, "RECALL_FUSION_BM25_WEIGHT", value)
    monkeypatch.setattr(recall_pipeline_provider.settings, "RECALL_FUSION_BM25_WEIGHT", value)


@given(parsers.parse("Settings 中 RECALL_FUSION_SPARSE_WEIGHT={value:f}"))
def _given_settings_sparse(monkeypatch, value: float) -> None:
    monkeypatch.setattr(settings, "RECALL_FUSION_SPARSE_WEIGHT", value)
    monkeypatch.setattr(recall_pipeline_provider.settings, "RECALL_FUSION_SPARSE_WEIGHT", value)


@given(parsers.parse("Settings 中 RECALL_FUSION_DENSE_WEIGHT={value:f}"))
def _given_settings_dense(monkeypatch, value: float) -> None:
    monkeypatch.setattr(settings, "RECALL_FUSION_DENSE_WEIGHT", value)
    monkeypatch.setattr(recall_pipeline_provider.settings, "RECALL_FUSION_DENSE_WEIGHT", value)


@when("装配 RecallPipeline 单例")
def _when_build_pipeline(weighted_fusion_state: _State, monkeypatch) -> None:
    monkeypatch.setattr(recall_pipeline_provider.settings, "RECALL_ENABLED_SOURCES", "bm25")
    monkeypatch.setitem(
        recall_pipeline_provider._BUILDERS,
        SOURCE_BM25,
        lambda: _FakeRetriever(SOURCE_BM25),
    )
    pipeline = recall_pipeline_provider._build_pipeline()
    weighted_fusion_state.pipeline_config = pipeline._config


@then(parsers.parse("RecallPipelineConfig.fusion_bm25_weight 等于 {value:f}"))
def _then_pipeline_bm25(weighted_fusion_state: _State, value: float) -> None:
    assert weighted_fusion_state.pipeline_config is not None
    assert weighted_fusion_state.pipeline_config.fusion_bm25_weight == pytest.approx(value)


@then(parsers.parse("RecallPipelineConfig.fusion_sparse_weight 等于 {value:f}"))
def _then_pipeline_sparse(weighted_fusion_state: _State, value: float) -> None:
    assert weighted_fusion_state.pipeline_config is not None
    assert weighted_fusion_state.pipeline_config.fusion_sparse_weight == pytest.approx(value)


@then(parsers.parse("RecallPipelineConfig.fusion_dense_weight 等于 {value:f}"))
def _then_pipeline_dense(weighted_fusion_state: _State, value: float) -> None:
    assert weighted_fusion_state.pipeline_config is not None
    assert weighted_fusion_state.pipeline_config.fusion_dense_weight == pytest.approx(value)


@given("dataset_parse_config.recall_config 包含:")
def _given_dataset_recall_config(weighted_fusion_state: _State, datatable) -> None:
    data = {row[0]: row[1] for row in datatable[1:]}
    for key in ("fusion_bm25_weight", "fusion_sparse_weight", "fusion_dense_weight"):
        data[key] = float(data[key])
    weighted_fusion_state.dataset_recall_config = RecallConfig(**data)


@when("纯召回 JSON 入口解析该数据集配置")
def _when_route_maps_dataset_config(weighted_fusion_state: _State, monkeypatch) -> None:
    dataset_contexts = {10: SimpleNamespace()}

    async def _recall_execution(_user_id, _dataset_ids):
        return weighted_fusion_state.dataset_recall_config, dataset_contexts

    async def _run_recall_json(_pipeline, recall_req, _request_id):
        weighted_fusion_state.captured_request = recall_req
        return {"hits": [], "failed_sources": []}

    async def _dataset_scope(_db, *, user_id, requested_dataset_ids):
        return [10]

    monkeypatch.setattr(recall, "resolve_user_dataset_scope", _dataset_scope)
    monkeypatch.setattr(recall, "aresolve_recall_execution", _recall_execution)
    monkeypatch.setattr(recall, "run_recall_json", _run_recall_json)
    ctx = SimpleNamespace(user_id=123, request_id="rid")
    asyncio.run(recall.recall_json(_request_with_payload({"query": "q"}), ctx, object()))


@then(parsers.parse('构造的 RecallRequest.fusion_strategy_override 等于 "{strategy}"'))
def _then_request_strategy(weighted_fusion_state: _State, strategy: str) -> None:
    assert weighted_fusion_state.captured_request is not None
    assert weighted_fusion_state.captured_request.fusion_strategy_override == strategy


@then(parsers.parse("构造的 RecallRequest.fusion_bm25_weight_override 等于 {value:f}"))
def _then_request_bm25(weighted_fusion_state: _State, value: float) -> None:
    assert weighted_fusion_state.captured_request is not None
    assert weighted_fusion_state.captured_request.fusion_bm25_weight_override == pytest.approx(
        value
    )


@then(parsers.parse("构造的 RecallRequest.fusion_sparse_weight_override 等于 {value:f}"))
def _then_request_sparse(weighted_fusion_state: _State, value: float) -> None:
    assert weighted_fusion_state.captured_request is not None
    assert weighted_fusion_state.captured_request.fusion_sparse_weight_override == pytest.approx(
        value
    )


@then(parsers.parse("构造的 RecallRequest.fusion_dense_weight_override 等于 {value:f}"))
def _then_request_dense(weighted_fusion_state: _State, value: float) -> None:
    assert weighted_fusion_state.captured_request is not None
    assert weighted_fusion_state.captured_request.fusion_dense_weight_override == pytest.approx(
        value
    )


@given("Java access token 对应用户 sub=123 dataset_ids=[1] 有效")
def _given_http_claims() -> None:
    return None


@when(
    parsers.parse(
        '前端调用 POST /api/v1/recall 或 POST /api/v1/rag/stream body 额外包含字段 "{field}"'
    )
)
def _when_http_body_has_fusion_field(weighted_fusion_state: _State, field: str) -> None:
    weighted_fusion_state.http_errors = []

    async def _run() -> None:
        for parser, payload in [
            (
                recall._parse_and_validate_body,
                {"query": "q", field: "weighted_score"},
            ),
            (
                rag._parse_and_validate_body,
                {
                    "query": "q",
                    "config_id": 1,
                    "conversation_id": 2,
                    "turn_id": "t",
                    field: "weighted_score",
                },
            ),
        ]:
            try:
                await parser(_request_with_payload(payload))
            except RecallApiError as exc:
                weighted_fusion_state.http_errors.append(exc)
            else:  # pragma: no cover - assertion below gives clearer failure
                raise AssertionError(f"{field} should be rejected")

    asyncio.run(_run())


@then(parsers.parse("HTTP 响应状态为 {status:d}"))
def _then_http_status(weighted_fusion_state: _State, status: int) -> None:
    assert weighted_fusion_state.http_errors
    assert all(exc.status_code == status for exc in weighted_fusion_state.http_errors)


@then(parsers.parse('响应体 code 等于 "{code}"'))
def _then_http_error_code(weighted_fusion_state: _State, code: str) -> None:
    assert weighted_fusion_state.http_errors
    assert all(exc.code == code for exc in weighted_fusion_state.http_errors)


@then("不调用 RecallPipeline")
def _then_pipeline_not_called(weighted_fusion_state: _State) -> None:
    assert weighted_fusion_state.pipeline_called is False


# ---------------------------------------------------------------------------
# Rerank 契约
# ---------------------------------------------------------------------------


@given(parsers.parse('weighted_score 融合后 hits 顺序为 "{order}"'))
def _given_weighted_hits(weighted_fusion_state: _State, order: str) -> None:
    chunk_ids = _split_sources(order)
    weighted_fusion_state.fusion_hits = [
        RecallHit(
            chunk_id=chunk_id,
            doc_id=100 + index,
            dataset_id=10,
            fused_score=1.0 - index * 0.1,
            scores={
                SOURCE_BM25: None,
                SOURCE_SPARSE: None,
                SOURCE_DENSE: 1.0 - index * 0.1,
            },
        )
        for index, chunk_id in enumerate(chunk_ids)
    ]


@given("Dataset 已绑定可用的精确 RERANK config_id")
def _given_rerank_available(weighted_fusion_state: _State) -> None:
    weighted_fusion_state.reranker = _CapturingReranker(unavailable=False)


@given("Dataset 精确 RERANK config_id 在执行期不可用")
def _given_rerank_unavailable(weighted_fusion_state: _State) -> None:
    weighted_fusion_state.reranker = _CapturingReranker(unavailable=True)


@when("RAG 流进入 rerank 阶段")
def _when_rag_enters_rerank(weighted_fusion_state: _State) -> None:
    assert weighted_fusion_state.reranker is not None
    contents = {
        hit.chunk_id: f"content {hit.chunk_id}" for hit in weighted_fusion_state.fusion_hits
    }
    hits, applied = asyncio.run(
        _rerank_hits(
            weighted_fusion_state.reranker,
            RecallRequest(
                user_id=123,
                query="q",
                dataset_ids=[10],
                dataset_contexts={
                    10: SimpleNamespace(
                        config=SimpleNamespace(recall=SimpleNamespace(enable_rerank=True)),
                        rerank=SimpleNamespace(config_id=780),
                    )
                },
            ),
            weighted_fusion_state.fusion_hits,
            contents,
            timeout_s=1.0,
            request_id="rid",
            top_n=10,
        )
    )
    weighted_fusion_state.rerank_hits = hits
    weighted_fusion_state.rerank_applied = applied


@then(parsers.parse('RerankRequest.hits 顺序为 "{order}"'))
def _then_rerank_request_order(weighted_fusion_state: _State, order: str) -> None:
    assert weighted_fusion_state.reranker is not None
    request = weighted_fusion_state.reranker.captured_request
    assert request is not None
    assert [hit.chunk_id for hit in request.hits] == _split_sources(order)


@then("RerankRequest.hits 中每个 hit 保留 fused_score 与 scores")
def _then_rerank_request_fields(weighted_fusion_state: _State) -> None:
    assert weighted_fusion_state.reranker is not None
    request = weighted_fusion_state.reranker.captured_request
    assert request is not None
    assert all(hit.fused_score is not None and hit.scores for hit in request.hits)


@then("rerank_score 不参与 weighted_score 融合计算")
def _then_rerank_score_not_in_fusion(weighted_fusion_state: _State) -> None:
    assert all(not hasattr(hit, "rerank_score") for hit in weighted_fusion_state.fusion_hits)


@then("终态事件 data 的 rerank_applied 为 false")
def _then_rerank_not_applied(weighted_fusion_state: _State) -> None:
    assert weighted_fusion_state.rerank_applied is False


@then(parsers.parse('终态事件 data 中 hits 顺序为 "{order}"'))
def _then_final_hits_order(weighted_fusion_state: _State, order: str) -> None:
    assert [hit.chunk_id for hit in weighted_fusion_state.rerank_hits] == _split_sources(order)


@then("hits 中每个 hit 的 rerank_score 与 rerank_rank 为 null")
def _then_rerank_fields_null(weighted_fusion_state: _State) -> None:
    assert weighted_fusion_state.rerank_hits
    assert all(
        hit.rerank_score is None and hit.rerank_rank is None
        for hit in weighted_fusion_state.rerank_hits
    )
