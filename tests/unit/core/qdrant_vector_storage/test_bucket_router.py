from __future__ import annotations

import zlib

import pytest

from src.core.qdrant_vector_storage import BucketRouter


def test_should_route_user_to_stable_bucket_when_user_id_provided():
    router = BucketRouter(bucket_count=8, prefix="test_bucket")

    route = router.route_user(42)

    expected_bucket_id = zlib.crc32(b"42") % 8
    assert route.bucket_id == expected_bucket_id
    assert route.collection_name == f"test_bucket_{expected_bucket_id}"
    assert router.route_user(42) == route


def test_should_reject_invalid_bucket_config_when_bucket_count_or_prefix_invalid():
    with pytest.raises(ValueError, match="bucket_count"):
        BucketRouter(bucket_count=0, prefix="test_bucket")

    with pytest.raises(ValueError, match="prefix"):
        BucketRouter(bucket_count=1, prefix="")

    router = BucketRouter(bucket_count=1, prefix="test_bucket")
    with pytest.raises(ValueError, match="bucket_id"):
        router.collection_name(1)
