"""封装分片向量索引所需的 Qdrant 操作。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.config import settings

from ..bucket_router import BucketRouter
from ..constants import (
    DEFAULT_BUCKET_COUNT,
    DEFAULT_COLLECTION_PREFIX,
    DEFAULT_QDRANT_TIMEOUT_SECONDS,
    QDRANT_PAYLOAD_INDEX_FIELDS,
)
from ..exceptions import QdrantStoreError, VectorStorageConfigurationError
from ..models import IndexedPoint


class QdrantIndexStore:
    """
        封装所有 Qdrant collection 与 point 的可靠操作，不直接承担业务编排决策。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(
        self,
        *,
        client: Any | None = None,
        bucket_router: BucketRouter | None = None,
        host: str | None = None,
        port: int | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
        prefer_grpc: bool = False,
    ) -> None:
        """
            初始化 Qdrant 存储访问层，并准备连接参数、分桶路由与客户端复用策略。

        Args:
            client: 可选的外部注入 Qdrant 异步客户端实例。
            bucket_router: 负责生成 collection 名称的分桶路由器。
            host: Qdrant 服务主机地址。
            port: Qdrant 服务端口。
            api_key: 可选的访问鉴权密钥。
            timeout: 单次请求超时时间。
            prefer_grpc: 是否优先使用 gRPC 传输。

        Returns:
            None.
        """
        self._client = client
        self._owns_client = client is None
        self.bucket_router = bucket_router or BucketRouter(
            bucket_count=getattr(settings, "CHUNK_INDEX_BUCKET_COUNT", DEFAULT_BUCKET_COUNT),
            prefix=getattr(settings, "CHUNK_INDEX_COLLECTION_PREFIX", DEFAULT_COLLECTION_PREFIX),
        )
        self.host = host or settings.QDRANT_HOST
        self.port = port or settings.QDRANT_PORT
        self.api_key = api_key if api_key is not None else getattr(settings, "QDRANT_API_KEY", None)
        self.timeout = timeout or getattr(
            settings,
            "QDRANT_TIMEOUT_SECONDS",
            DEFAULT_QDRANT_TIMEOUT_SECONDS,
        )
        self.prefer_grpc = prefer_grpc
        self._payload_index_ready_collections: set[str] = set()

    async def ensure_collection(
        self,
        *,
        bucket_id: int,
        vector_size: int,
    ) -> None:
        """
            确保目标桶对应的 collection 存在，并为过滤字段建立 payload 索引。

        Args:
            bucket_id: 当前需要初始化的物理桶编号。
            vector_size: 目标 collection 使用的向量维度。

        Returns:
            None.
        """
        if vector_size <= 0:
            raise ValueError("vector_size must be positive.")

        client = await self._get_client()
        models = self._models()
        collection_name = self.bucket_router.collection_name(bucket_id)

        try:
            exists = await client.collection_exists(collection_name=collection_name)
            if not exists:
                await client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                    ),
                )

            if collection_name not in self._payload_index_ready_collections:
                for field_name in QDRANT_PAYLOAD_INDEX_FIELDS:
                    await client.create_payload_index(
                        collection_name=collection_name,
                        field_name=field_name,
                        field_schema=models.PayloadSchemaType.INTEGER,
                        wait=True,
                    )
                self._payload_index_ready_collections.add(collection_name)
        except Exception as exc:
            raise QdrantStoreError(
                f"Failed to ensure Qdrant collection {collection_name}: {exc}"
            ) from exc

    async def upsert_points(
        self,
        *,
        bucket_id: int,
        points: Sequence[IndexedPoint],
    ) -> None:
        """
            将一批标准化 point 批量 upsert 到目标桶对应的 Qdrant collection。

        Args:
            bucket_id: 当前写入目标的物理桶编号。
            points: 待写入的 point 序列。

        Returns:
            None.
        """
        if not points:
            return

        client = await self._get_client()
        models = self._models()
        collection_name = self.bucket_router.collection_name(bucket_id)
        qdrant_points = [
            models.PointStruct(
                id=point.chunk_id,
                vector=point.vector,
                payload=point.payload,
            )
            for point in points
        ]

        try:
            await client.upsert(
                collection_name=collection_name,
                points=qdrant_points,
                wait=True,
            )
        except Exception as exc:
            raise QdrantStoreError(f"Failed to upsert points into {collection_name}: {exc}") from exc

    async def point_exists(
        self,
        *,
        bucket_id: int,
        chunk_id: str,
    ) -> bool:
        """
            检查指定 `chunk_id` 对应的 point 是否已经存在于目标桶 collection 中。

        Args:
            bucket_id: 需要检查的物理桶编号。
            chunk_id: 目标 point 的业务唯一标识。

        Returns:
            bool: point 是否已存在。
        """
        client = await self._get_client()
        collection_name = self.bucket_router.collection_name(bucket_id)

        try:
            exists = await client.collection_exists(collection_name=collection_name)
            if not exists:
                return False
            records = await client.retrieve(
                collection_name=collection_name,
                ids=[chunk_id],
                with_payload=False,
                with_vectors=False,
            )
        except Exception as exc:
            raise QdrantStoreError(
                f"Failed to check point existence in {collection_name}: {exc}"
            ) from exc

        return bool(records)

    async def delete_points(
        self,
        *,
        bucket_id: int,
        chunk_ids: Sequence[str],
    ) -> None:
        """
            从目标桶 collection 中批量删除指定 `chunk_id` 对应的 points。

        Args:
            bucket_id: 当前删除目标的物理桶编号。
            chunk_ids: 需要删除的 point 标识列表。

        Returns:
            None.
        """
        if not chunk_ids:
            return

        client = await self._get_client()
        collection_name = self.bucket_router.collection_name(bucket_id)

        try:
            exists = await client.collection_exists(collection_name=collection_name)
            if not exists:
                return
            await client.delete(
                collection_name=collection_name,
                points_selector=list(chunk_ids),
                wait=True,
            )
        except Exception as exc:
            raise QdrantStoreError(f"Failed to delete points from {collection_name}: {exc}") from exc

    async def close(self) -> None:
        """
            关闭由当前对象自行创建并持有的 Qdrant 客户端连接。

        Args:
            None.

        Returns:
            None.
        """
        if self._owns_client and self._client is not None and hasattr(self._client, "close"):
            await self._client.close()
            self._client = None

    async def _get_client(self) -> Any:
        """
            获取可用的 Qdrant 异步客户端；如尚未创建则按配置动态初始化。

        Args:
            None.

        Returns:
            Any: 可执行异步请求的 Qdrant 客户端实例。
        """
        if self._client is not None:
            return self._client

        client_cls = self._client_class()
        self._client = client_cls(
            host=self.host,
            port=self.port,
            api_key=self.api_key,
            timeout=self.timeout,
            prefer_grpc=self.prefer_grpc,
        )
        return self._client

    def _client_class(self) -> Any:
        """
            延迟解析 Qdrant 异步客户端类型，并在依赖缺失时抛出配置异常。

        Args:
            None.

        Returns:
            Any: `AsyncQdrantClient` 类对象。
        """
        try:
            from qdrant_client import AsyncQdrantClient
        except ImportError as exc:
            raise VectorStorageConfigurationError(
                "qdrant-client is required to use QdrantIndexStore."
            ) from exc
        return AsyncQdrantClient

    def _models(self) -> Any:
        """
            延迟解析 Qdrant 模型命名空间，供 collection 与 point 构造时复用。

        Args:
            None.

        Returns:
            Any: `qdrant_client.models` 模块对象。
        """
        try:
            from qdrant_client import models
        except ImportError as exc:
            raise VectorStorageConfigurationError(
                "qdrant-client is required to use QdrantIndexStore."
            ) from exc
        return models
