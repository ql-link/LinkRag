from src.core.vector_storage import (
    RepairDecision,
    RepairPolicy,
    VectorStorageCompensationPipeline,
    VectorStorageManagementPipeline,
    VectorStoragePipeline,
)
from src.core.chunk_fact_storage.constants import (
    CHUNK_STATUS_FAILED,
    CHUNK_STATUS_PENDING,
)


def test_should_expose_documented_pipeline_classes_as_service_compatible_entrypoints(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
):
    storage_pipeline = VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=mock_embedding_pipeline,
    )
    management_pipeline = VectorStorageManagementPipeline(
        session_factory=mock_session_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=mock_embedding_pipeline,
    )
    compensation_pipeline = VectorStorageCompensationPipeline(
        session_factory=mock_session_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
    )

    assert storage_pipeline.__class__ is VectorStoragePipeline
    assert management_pipeline.__class__ is VectorStorageManagementPipeline
    assert compensation_pipeline.__class__ is VectorStorageCompensationPipeline


def test_should_keep_repair_policy_conservative_for_vectorization_failures():
    policy = RepairPolicy(max_delete_retry_limit=50)

    assert policy.normalize_limit(100) == 50
    assert policy.normalize_limit(0) == 0
    assert (
        policy.decide_for_status(CHUNK_STATUS_PENDING, point_exists=True)
        == RepairDecision.LIGHTWEIGHT_STATUS_REPAIR
    )
    assert (
        policy.decide_for_status(CHUNK_STATUS_PENDING, point_exists=False)
        == RepairDecision.MANUAL_REINDEX_REQUIRED
    )
    assert policy.decide_for_status(CHUNK_STATUS_FAILED) == RepairDecision.MANUAL_REINDEX_REQUIRED
