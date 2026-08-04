"""按 dataset_id 直接映射 Manticore 表名。

Manticore 按 ``dataset_id`` 精确建表，一个 dataset 一张表，没有哈希、没有共享，
表名与 dataset 是一一对应关系。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class TableRoute:
    """描述一个 dataset 对应的 Manticore 表名。"""

    dataset_id: int
    table_name: str


class TableRouter:
    """按 dataset_id 生成 Manticore 表名，一一对应，无分桶。"""

    def __init__(self, prefix: str) -> None:
        if not prefix:
            raise ValueError("prefix must not be empty.")
        if not _SQL_IDENTIFIER.fullmatch(prefix):
            raise ValueError(
                "prefix must be a safe SQL identifier: letters, digits and underscores only"
            )
        self.prefix = prefix

    def route_dataset(self, dataset_id: int) -> TableRoute:
        return TableRoute(dataset_id=dataset_id, table_name=self.table_name(dataset_id))

    def table_name(self, dataset_id: int) -> str:
        if dataset_id <= 0:
            raise ValueError(f"dataset_id must be positive, got {dataset_id}.")
        return f"{self.prefix}_{dataset_id}"
