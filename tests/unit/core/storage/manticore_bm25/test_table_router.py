"""TableRouter 单元测试：按 dataset_id 精确建表名，不哈希、不分桶。"""

import pytest

from src.core.storage.manticore_bm25.table_router import TableRouter


def test_table_name_is_deterministic_per_dataset() -> None:
    router = TableRouter(prefix="bm25_ds")
    assert router.table_name(1) == "bm25_ds_1"
    assert router.table_name(42) == "bm25_ds_42"
    # 同一个 dataset_id 永远映射到同一张表。
    assert router.table_name(42) == router.table_name(42)


def test_route_dataset_returns_route() -> None:
    router = TableRouter(prefix="bm25_ds")
    route = router.route_dataset(7)
    assert route.dataset_id == 7
    assert route.table_name == "bm25_ds_7"


def test_rejects_non_positive_dataset_id() -> None:
    router = TableRouter(prefix="bm25_ds")
    with pytest.raises(ValueError):
        router.table_name(0)
    with pytest.raises(ValueError):
        router.table_name(-1)


def test_rejects_empty_prefix() -> None:
    with pytest.raises(ValueError):
        TableRouter(prefix="")
