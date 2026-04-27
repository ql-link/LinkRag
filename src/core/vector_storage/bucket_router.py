"""提供 Qdrant 集合分桶路由与命名辅助能力。"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from .constants import DEFAULT_BUCKET_COUNT, DEFAULT_COLLECTION_PREFIX


@dataclass(frozen=True, slots=True)
class BucketRoute:
    """
        描述单个用户在向量分桶策略下命中的物理桶编号与对应集合名称。

    Args:
        None.

    Returns:
        None.
    """

    bucket_id: int
    collection_name: str


class BucketRouter:
    """
        负责根据用户标识计算稳定分桶结果，并统一生成 Qdrant collection 名称。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(
        self,
        bucket_count: int = DEFAULT_BUCKET_COUNT,
        prefix: str = DEFAULT_COLLECTION_PREFIX,
    ) -> None:
        """
            初始化分桶路由器，并校验桶数量与 collection 前缀是否合法。

        Args:
            bucket_count: 可用的物理桶总数。
            prefix: Qdrant collection 的统一命名前缀。

        Returns:
            None.
        """
        if bucket_count <= 0:
            raise ValueError("bucket_count must be positive.")
        if not prefix:
            raise ValueError("prefix must not be empty.")

        self.bucket_count = bucket_count
        self.prefix = prefix

    def route_user(self, user_id: int) -> BucketRoute:
        """
            根据 `user_id` 计算稳定分桶结果，并返回包含桶编号与集合名的路由对象。

        Args:
            user_id: 需要参与分桶计算的用户标识。

        Returns:
            BucketRoute: 当前用户命中的分桶路由结果。
        """
        bucket_id = zlib.crc32(str(user_id).encode("utf-8")) % self.bucket_count
        return BucketRoute(bucket_id=bucket_id, collection_name=self.collection_name(bucket_id))

    def collection_name(self, bucket_id: int) -> str:
        """
            根据桶编号生成标准化的 Qdrant collection 名称。

        Args:
            bucket_id: 已计算完成的物理桶编号。

        Returns:
            str: 对应的 Qdrant collection 名称。
        """
        if bucket_id < 0 or bucket_id >= self.bucket_count:
            raise ValueError(
                f"bucket_id must be in range [0, {self.bucket_count}), got {bucket_id}."
            )
        return f"{self.prefix}_{bucket_id}"
