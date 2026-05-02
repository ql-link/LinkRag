from unittest.mock import MagicMock

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
    assert facade.storage_service.qdrant_store is mock_qdrant_store
    assert facade.management_service.qdrant_store is mock_qdrant_store
    assert facade.compensation_service.qdrant_store is mock_qdrant_store
