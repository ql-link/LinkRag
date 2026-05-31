"""根据用户 ID 计算 Qdrant 分桶 collection。"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from .constants import DEFAULT_BUCKET_COUNT, DEFAULT_COLLECTION_PREFIX


@dataclass(frozen=True, slots=True)
class BucketRoute:
    """描述用户命中的 Qdrant 分桶和 collection 名称。"""

    bucket_id: int
    collection_name: str


class BucketRouter:
    """按用户 ID 稳定路由到固定数量的 Qdrant 分桶。"""

    def __init__(
        self,
        bucket_count: int = DEFAULT_BUCKET_COUNT,
        prefix: str = DEFAULT_COLLECTION_PREFIX,
    ) -> None:
        """初始化分桶数量和 collection 名称前缀。"""

        if bucket_count <= 0:
            raise ValueError("bucket_count must be positive.")
        if not prefix:
            raise ValueError("prefix must not be empty.")

        self.bucket_count = bucket_count
        self.prefix = prefix

    def route_user(self, user_id: int) -> BucketRoute:
        """根据用户 ID 计算稳定分桶路由。"""

        bucket_id = zlib.crc32(str(user_id).encode("utf-8")) % self.bucket_count
        return BucketRoute(bucket_id=bucket_id, collection_name=self.collection_name(bucket_id))

    def collection_name(self, bucket_id: int) -> str:
        """按分桶编号生成 Qdrant collection 名称。"""

        if bucket_id < 0 or bucket_id >= self.bucket_count:
            raise ValueError(
                f"bucket_id must be in range [0, {self.bucket_count}), got {bucket_id}."
            )
        return f"{self.prefix}_{bucket_id}"
