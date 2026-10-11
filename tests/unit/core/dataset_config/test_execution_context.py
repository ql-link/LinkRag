"""DatasetExecutionContext 在 provider 调用前冻结五类绑定。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.dataset_config.execution_context import (
    DatasetExecutionContextLoader,
    DatasetExecutionPurpose,
)
from src.core.dataset_config.models import (
    DatasetModelBindingConfig,
    DatasetParseConfigBundle,
    EnhancementConfig,
    RecallConfig,
)
from src.core.llm.exceptions import DatasetModelBindingRequiredError


class _ConfigService:
    def __init__(self, bundle: DatasetParseConfigBundle) -> None:
        self.bundle = bundle
        self.calls: list[tuple[int, int]] = []

    async def get_config(self, user_id, dataset_id, db):
        self.calls.append((user_id, dataset_id))
        return self.bundle


def _bundle(
    *,
    table: bool = False,
    image: bool = False,
    heading: bool = False,
    rerank: bool = False,
    **bindings,
) -> DatasetParseConfigBundle:
    return DatasetParseConfigBundle(
        enhancement=EnhancementConfig(
            enable_table_enhancement=table,
            enable_image_enhancement=image,
            enable_heading_hierarchy=heading,
        ),
        recall=RecallConfig(enable_rerank=rerank),
        model_bindings=DatasetModelBindingConfig(**bindings),
    )


@pytest.mark.asyncio
async def test_parse_requires_dense_sparse_and_enabled_enhancement_bindings(monkeypatch):
    bundle = _bundle(
        table=True,
        image=True,
        heading=True,
        dense_embedding_config_id=11,
        sparse_embedding_config_id=12,
    )
    loader = DatasetExecutionContextLoader(
        object(), config_service=_ConfigService(bundle), repository=object()
    )

    with pytest.raises(DatasetModelBindingRequiredError) as exc:
        await loader.load(7, 99, DatasetExecutionPurpose.PARSE)

    assert exc.value.dataset_id == 99
    assert exc.value.missing_bindings == [
        "enhancement_chat_config_id",
        "enhancement_vision_config_id",
    ]


@pytest.mark.asyncio
async def test_parse_resolves_each_required_binding_with_exact_capability(monkeypatch):
    calls: list[dict] = []

    async def _resolve(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(config_id=kwargs["config_id"], provider=object())

    monkeypatch.setattr("src.core.dataset_config.execution_context.aresolve_model", _resolve)
    bundle = _bundle(
        table=True,
        image=True,
        heading=True,
        dense_embedding_config_id=11,
        sparse_embedding_config_id=12,
        enhancement_chat_config_id=13,
        enhancement_vision_config_id=14,
        rerank_config_id=15,
    )
    loader = DatasetExecutionContextLoader(
        object(), config_service=_ConfigService(bundle), repository=object()
    )

    context = await loader.load(7, 99, DatasetExecutionPurpose.PARSE)

    assert [(item["config_id"], item["capability"]) for item in calls] == [
        (11, "EMBEDDING"),
        (12, "SPARSE_EMBEDDING"),
        (13, "CHAT"),
        (14, "VISION"),
    ]
    assert context.rerank is None
    assert context.enhancement_chat.config_id == 13
    assert all(item["repository"] is loader._repository for item in calls)


@pytest.mark.asyncio
async def test_recall_only_requires_rerank_when_explicitly_enabled(monkeypatch):
    calls: list[tuple[int, str]] = []

    async def _resolve(**kwargs):
        calls.append((kwargs["config_id"], kwargs["capability"]))
        return SimpleNamespace(config_id=kwargs["config_id"], provider=object())

    monkeypatch.setattr("src.core.dataset_config.execution_context.aresolve_model", _resolve)
    bundle = _bundle(
        rerank=False,
        dense_embedding_config_id=21,
        sparse_embedding_config_id=22,
    )
    loader = DatasetExecutionContextLoader(
        object(), config_service=_ConfigService(bundle), repository=object()
    )

    context = await loader.load(7, 100, DatasetExecutionPurpose.RECALL)

    assert calls == [(21, "EMBEDDING"), (22, "SPARSE_EMBEDDING")]
    assert context.rerank is None

    enabled = _bundle(
        rerank=True,
        dense_embedding_config_id=21,
        sparse_embedding_config_id=22,
    )
    with pytest.raises(DatasetModelBindingRequiredError) as exc:
        await DatasetExecutionContextLoader(
            object(), config_service=_ConfigService(enabled), repository=object()
        ).load(7, 100, DatasetExecutionPurpose.RECALL)
    assert exc.value.missing_bindings == ["rerank_config_id"]


@pytest.mark.asyncio
async def test_load_many_keeps_dataset_contexts_separate(monkeypatch):
    bundles = {
        1: _bundle(dense_embedding_config_id=101, sparse_embedding_config_id=102),
        2: _bundle(dense_embedding_config_id=201, sparse_embedding_config_id=202),
    }

    class _PerDatasetConfig:
        async def get_config(self, user_id, dataset_id, db):
            return bundles[dataset_id]

    async def _resolve(**kwargs):
        return SimpleNamespace(config_id=kwargs["config_id"], provider=object())

    monkeypatch.setattr("src.core.dataset_config.execution_context.aresolve_model", _resolve)
    loader = DatasetExecutionContextLoader(
        object(), config_service=_PerDatasetConfig(), repository=object()
    )

    contexts = await loader.load_many(7, [1, 2, 1], DatasetExecutionPurpose.RECALL)

    assert list(contexts) == [1, 2]
    assert contexts[1].dense_embedding.config_id == 101
    assert contexts[2].dense_embedding.config_id == 201


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", list(DatasetExecutionPurpose))
async def test_doubao_dense_sparse_share_one_http_response(monkeypatch, purpose):
    """真实装配两种 encoder，覆盖并发、不同批次及用量只记一次。"""
    import asyncio
    import json

    import httpx

    from src.core.encoding.sparse.factory import build_sparse_vector_service
    from src.core.llm.providers.doubao_vision import DoubaoVisionProvider
    from src.core.llm.user_model_resolver import ResolvedModel
    from src.core.splitter.factory import build_chunk_embedding_pipeline
    from src.core.splitter.models import Chunk

    requests = []
    providers = []
    usage_events = []
    monkeypatch.setattr(
        "src.services.usage_reporter.report_usage_nowait",
        lambda **event: usage_events.append(event),
    )

    async def handler(request):
        body = json.loads(request.content)
        text = body["input"][0]["text"]
        requests.append(text)
        await asyncio.sleep(0)
        return httpx.Response(
            200,
            json={
                "data": {
                    "embedding": [float(len(text))] * 1024,
                    "sparse_embedding": [{"index": len(text), "value": 0.8}],
                },
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )

    async def resolve(**kwargs):
        provider = DoubaoVisionProvider(
            api_key="same-key",
            api_base_url="https://ark.example/embeddings/multimodal",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        providers.append(provider)
        return ResolvedModel(
            provider=provider,
            model_name=provider.DEFAULT_MODEL,
            provider_type="volcengine",
            protocol="doubao_vision",
            config_id=kwargs["config_id"],
            scope="SYSTEM",
            snapshot_version=1,
        )

    monkeypatch.setattr("src.core.dataset_config.execution_context.aresolve_model", resolve)
    loader = DatasetExecutionContextLoader(
        object(),
        repository=object(),
        config_service=_ConfigService(
            _bundle(
                dense_embedding_config_id=101,
                sparse_embedding_config_id=102,
            )
        ),
    )
    context = await loader.load(7, 100, purpose, task_id="parse-test")
    dense = build_chunk_embedding_pipeline(context.dense_embedding)
    dense.batch_size = 1
    sparse = build_sparse_vector_service(context.sparse_embedding)
    try:
        assert context.dense_embedding.config_id == 101
        assert context.sparse_embedding.config_id == 102
        if purpose is DatasetExecutionPurpose.PARSE:
            dense_result, sparse_result = await asyncio.gather(
                dense.aembed_chunks([Chunk("a", 1, 1), Chunk("bb", 2, 2)]),
                sparse.vectorize_texts(["bb", "a"]),
            )
            assert [item.embedding[0] for item in dense_result] == [1.0, 2.0]
            assert [item.indices for item in sparse_result] == [[2], [1]]
            total_tokens = dense.last_stats.total_tokens + sparse.last_usage.total_tokens
            assert sorted(requests) == ["a", "bb"]
            assert total_tokens == 0
            assert sum(event["total_tokens"] for event in usage_events) == 4
        else:
            (dense_result, dense_usage), sparse_result = await asyncio.gather(
                dense.aembed_query_detailed("question"),
                sparse.vectorize_query("question"),
            )
            assert dense_result == [8.0] * 1024
            assert sparse_result.indices == [8]
            assert requests == ["question"]
            assert dense_usage.total_tokens + sparse.last_usage.total_tokens == 0
            assert sum(event["total_tokens"] for event in usage_events) == 2
        # 多数据集召回仍分别解析绑定，但同一请求中等价配置只编码一次 query。
        contexts = await loader.load_many(7, [100, 101], purpose)
        before = len(requests)
        await asyncio.gather(
            *[
                call
                for item in contexts.values()
                for call in (
                    build_chunk_embedding_pipeline(item.dense_embedding).aembed_query("multi"),
                    build_sparse_vector_service(item.sparse_embedding).vectorize_query("multi"),
                )
            ]
        )
        assert requests[before:] == ["multi"]

        # 新一次 load 不复用上一任务的缓存，即使 user、dataset、文本完全相同。
        another = await loader.load(7, 100, purpose)
        await build_chunk_embedding_pipeline(another.dense_embedding).aembed_query("a")
        assert requests.count("a") == (2 if purpose is DatasetExecutionPurpose.PARSE else 1)
    finally:
        for provider in providers:
            await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("different", ["model", "endpoint", "key"])
async def test_doubao_different_request_identity_is_not_shared(monkeypatch, different):
    from src.core.llm.providers.doubao_vision import DoubaoVisionProvider
    from src.core.llm.user_model_resolver import ResolvedModel

    async def resolve(**kwargs):
        sparse = kwargs["capability"] == "SPARSE_EMBEDDING"
        model = "other-model" if sparse and different == "model" else "doubao-model"
        provider = DoubaoVisionProvider(
            api_key="other-key" if sparse and different == "key" else "key",
            api_base_url=(
                "https://other.example"
                if sparse and different == "endpoint"
                else "https://ark.example"
            ),
            model_name=model,
        )
        return ResolvedModel(
            provider, model, "volcengine", "doubao_vision", kwargs["config_id"], "SYSTEM", 1
        )

    monkeypatch.setattr("src.core.dataset_config.execution_context.aresolve_model", resolve)
    context = await DatasetExecutionContextLoader(
        object(),
        repository=object(),
        config_service=_ConfigService(
            _bundle(
                dense_embedding_config_id=101,
                sparse_embedding_config_id=102,
            )
        ),
    ).load(7, 100, DatasetExecutionPurpose.PARSE)
    assert context.dense_embedding.provider is not context.sparse_embedding.provider
