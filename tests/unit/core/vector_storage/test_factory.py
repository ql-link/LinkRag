from unittest.mock import MagicMock

import pytest

from src.config import settings
from src.core.vector_storage import VectorStorageFacade, create_vector_storage_facade
from src.core.vector_storage import (
    VectorStorageCompensationPipeline,
    VectorStorageManagementPipeline,
    VectorStoragePipeline,
)


def test_should_create_vector_storage_facade_with_injected_dependencies(
    mock_session_factory,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
):
    # Act: 执行动作
    facade = create_vector_storage_facade(
        session_factory=mock_session_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=mock_embedding_pipeline,
        bucket_router=MagicMock(),
    )

    # Assert: 断言结果
    assert isinstance(facade, VectorStorageFacade)
    assert isinstance(facade.storage_service, VectorStoragePipeline)
    assert isinstance(facade.management_service, VectorStorageManagementPipeline)
    assert isinstance(facade.compensation_service, VectorStorageCompensationPipeline)
    assert facade.storage_service.repository is mock_repository
    assert facade.management_service.repository is mock_repository
    assert facade.compensation_service.repository is mock_repository
    assert facade.compensation_service.embedding_pipeline is mock_embedding_pipeline
    assert facade.storage_service.qdrant_store is mock_qdrant_store
    assert facade.management_service.qdrant_store is mock_qdrant_store
    assert facade.compensation_service.qdrant_store is mock_qdrant_store


def test_should_inject_sparse_vector_service_into_facade_when_enabled(
    mock_session_factory,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    monkeypatch,
):
    """SPARSE_VECTOR_ENABLED=True 时，工厂构造的 sparse_vector_service 必须挂到
    facade 上，并与三个 pipeline 持有的是同一对象——保证写读 encoder 单实例。"""
    # autouse fixture 默认把 SPARSE_VECTOR_ENABLED 关掉；这里显式打开
    monkeypatch.setattr(settings, "SPARSE_VECTOR_ENABLED", True)

    sentinel_service = MagicMock(name="sparse_vector_service")
    sentinel_service.vector_name = "sparse_text"
    sentinel_service.model_name = "bge-m3-fake"

    import src.core.vector_storage.factory as factory_module

    monkeypatch.setattr(
        factory_module,
        "create_sparse_vector_service_from_settings",
        lambda: sentinel_service,
        raising=False,
    )
    # 工厂内的 import 路径是 ``from src.core.sparse_vector import ...``——补一份
    # patch，覆盖 factory 内部的延迟 import
    import src.core.sparse_vector as sparse_module

    monkeypatch.setattr(
        sparse_module,
        "create_sparse_vector_service_from_settings",
        lambda: sentinel_service,
        raising=True,
    )

    facade = create_vector_storage_facade(
        session_factory=mock_session_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=mock_embedding_pipeline,
        bucket_router=MagicMock(),
    )

    # facade._sparse_vector_service 与三个 pipeline 的同名字段同源
    assert facade._sparse_vector_service is sentinel_service
    assert facade.storage_service.sparse_vector_service is sentinel_service
    assert facade.management_service.sparse_vector_service is sentinel_service
    assert facade.compensation_service.sparse_vector_service is sentinel_service


def test_should_pass_none_when_sparse_vector_disabled(
    mock_session_factory,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
):
    """SPARSE_VECTOR_ENABLED=False（autouse fixture 默认值）时，
    facade 应当持有 None；召回入口被调用时由 facade 抛 ConfigurationError。"""
    facade = create_vector_storage_facade(
        session_factory=mock_session_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=mock_embedding_pipeline,
        bucket_router=MagicMock(),
    )

    assert facade._sparse_vector_service is None
