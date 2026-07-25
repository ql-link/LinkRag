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

    monkeypatch.setattr(
        "src.core.dataset_config.execution_context.aresolve_model", _resolve
    )
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

    monkeypatch.setattr(
        "src.core.dataset_config.execution_context.aresolve_model", _resolve
    )
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

    monkeypatch.setattr(
        "src.core.dataset_config.execution_context.aresolve_model", _resolve
    )
    loader = DatasetExecutionContextLoader(
        object(), config_service=_PerDatasetConfig(), repository=object()
    )

    contexts = await loader.load_many(7, [1, 2, 1], DatasetExecutionPurpose.RECALL)

    assert list(contexts) == [1, 2]
    assert contexts[1].dense_embedding.config_id == 101
    assert contexts[2].dense_embedding.config_id == 201
