from src.core.storage.vector import (
    RepairDecision,
    RepairPolicy,
)
from src.core.storage.chunks.constants import (
    CHUNK_STATUS_FAILED,
    CHUNK_STATUS_PENDING,
)


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
