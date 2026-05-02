from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.config import settings

from .bucket_router import BucketRouter
from .constants import (
    DEFAULT_BUCKET_COUNT,
    DEFAULT_COLLECTION_PREFIX,
    DEFAULT_QDRANT_TIMEOUT_SECONDS,
    QDRANT_PAYLOAD_INDEX_FIELDS,
)
from .exceptions import QdrantStoreError, QdrantVectorStorageConfigurationError
from .models import IndexedPoint


class QdrantIndexStore:
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

    async def ensure_collection(self, *, bucket_id: int, vector_size: int) -> None:
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

    async def upsert_points(self, *, bucket_id: int, points: Sequence[IndexedPoint]) -> None:
        if not points:
            return

        client = await self._get_client()
        models = self._models()
        collection_name = self.bucket_router.collection_name(bucket_id)
        qdrant_points = [
            models.PointStruct(id=point.chunk_id, vector=point.vector, payload=point.payload)
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

    async def point_exists(self, *, bucket_id: int, chunk_id: str) -> bool:
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

    async def delete_points(self, *, bucket_id: int, chunk_ids: Sequence[str]) -> None:
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
        if self._owns_client and self._client is not None and hasattr(self._client, "close"):
            await self._client.close()
            self._client = None

    async def _get_client(self) -> Any:
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
        try:
            from qdrant_client import AsyncQdrantClient
        except ImportError as exc:
            raise QdrantVectorStorageConfigurationError(
                "qdrant-client is required to use QdrantIndexStore."
            ) from exc
        return AsyncQdrantClient

    def _models(self) -> Any:
        try:
            from qdrant_client import models
        except ImportError as exc:
            raise QdrantVectorStorageConfigurationError(
                "qdrant-client is required to use QdrantIndexStore."
            ) from exc
        return models
