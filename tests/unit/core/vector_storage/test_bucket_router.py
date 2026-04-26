import zlib

import pytest

from src.core.vector_storage.bucket_router import BucketRouter


def test_should_return_crc32_bucket_and_collection_name_when_route_user_called():
    # Arrange: 准备数据
    router = BucketRouter(bucket_count=128, prefix="kb_bucket")

    # Act: 执行动作
    route = router.route_user(123456)

    # Assert: 断言结果
    expected_bucket = zlib.crc32(b"123456") % 128
    assert route.bucket_id == expected_bucket
    assert route.collection_name == f"kb_bucket_{expected_bucket}"


def test_should_raise_value_error_when_collection_name_bucket_is_out_of_range():
    # Arrange: 准备数据
    router = BucketRouter(bucket_count=8, prefix="bucket")

    # Act / Assert: 断言异常
    with pytest.raises(ValueError):
        router.collection_name(8)


def test_should_raise_value_error_when_bucket_count_is_not_positive():
    # Act / Assert: 断言异常
    with pytest.raises(ValueError):
        BucketRouter(bucket_count=0)
