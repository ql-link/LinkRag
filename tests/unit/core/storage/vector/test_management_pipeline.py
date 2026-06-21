"""VectorStorageManagementPipeline 的稀疏向量 per-user 解析单测。

management 的 update_chunk 端到端流程由集成测试覆盖；本文件聚焦本次新增的
``_resolve_sparse_vector_service``（与 compensation 同构）：注入优先 + 按用户解析。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.core.storage.vector.management_pipeline as mgmt_module


def _pipeline(**over):
    kwargs = dict(
        session_factory=MagicMock(),
        repository=MagicMock(),
        qdrant_store=MagicMock(),
        embedding_pipeline=MagicMock(),
    )
    kwargs.update(over)
    return mgmt_module.VectorStorageManagementPipeline(**kwargs)


@pytest.mark.asyncio
async def test_resolve_sparse_service_prefers_injected(monkeypatch):
    async def fail_resolve(user_id):
        raise AssertionError("must not resolve per-user when service is injected")

    monkeypatch.setattr(mgmt_module, "aresolve_user_sparse_vector_service", fail_resolve)

    injected = SimpleNamespace(model_name="injected")
    pipe = _pipeline(sparse_vector_service=injected)

    assert await pipe._resolve_sparse_vector_service(5) is injected


@pytest.mark.asyncio
async def test_resolve_sparse_service_per_user_when_not_injected(monkeypatch):
    resolved = SimpleNamespace(model_name="user-bge-m3")
    resolver = AsyncMock(return_value=resolved)
    monkeypatch.setattr(mgmt_module, "aresolve_user_sparse_vector_service", resolver)

    pipe = _pipeline()  # 不注入 → 按 user_id 解析

    assert await pipe._resolve_sparse_vector_service(42) is resolved
    resolver.assert_awaited_once_with(42)
