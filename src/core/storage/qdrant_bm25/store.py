"""Qdrant BM25 独立存储：单 collection + payload filter 隔离租户。

与 dense/sparse_text 的 per-bucket collection **解耦**——BM25 是独立全文索引（对标
ES index），用自己的 sparse-only collection（named sparse vector 带
``Modifier.IDF``），靠 payload filter(user_id/dataset_id/doc_id) 隔离租户、不计分。

职责边界：本类封装一切 qdrant-client 细节（collection 生命周期、upsert、带 Formula
乘法类型权重的查询、按文档删除）；上层 retriever/pipeline 只传业务参数与中立的
:class:`EncodedSparseVector`，不接触 qdrant SDK 类型。client 管理沿用
``QdrantIndexStore`` 的约定（空 api_key 归一为 None，避免明文 HTTP 触发 SSL 错误）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.config import settings
from src.core.storage.qdrant.exceptions import (
    QdrantStoreError,
    QdrantVectorStorageConfigurationError,
)
from src.utils.logger import logger

from .encoder import EncodedSparseVector
from .schema import (
    PAYLOAD_CHUNK_ID,
    PAYLOAD_CHUNK_TYPE,
    PAYLOAD_DATASET_ID,
    PAYLOAD_DOC_ID,
    PAYLOAD_USER_ID,
)


@dataclass(frozen=True, slots=True)
class Bm25Point:
    """一个待写入 BM25 collection 的 chunk：BM25 sparse 向量 + 多租户/类型 payload。"""

    chunk_id: str
    doc_id: int
    user_id: int
    dataset_id: int
    chunk_type: str
    sparse_vector: EncodedSparseVector


@dataclass(frozen=True, slots=True)
class Bm25ScoredPoint:
    """一次查询命中的中立结果（不含 qdrant SDK 类型）。"""

    chunk_id: str
    doc_id: int
    score: float


class QdrantBm25Store:
    """BM25 专用 Qdrant collection 的访问封装。"""

    def __init__(
        self,
        *,
        client: Any | None = None,
        host: str | None = None,
        port: int | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
        collection_name: str | None = None,
        vector_name: str | None = None,
        prefer_grpc: bool = False,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self.host = host or settings.QDRANT_HOST
        self.port = port or settings.QDRANT_PORT
        resolved_api_key = (
            api_key if api_key is not None else getattr(settings, "QDRANT_API_KEY", None)
        )
        # 空串归一为 None：见 QdrantIndexStore 同款说明（非 None api_key 会强制 https）。
        self.api_key = resolved_api_key or None
        self.timeout = timeout or getattr(settings, "QDRANT_TIMEOUT_SECONDS", 30)
        self.collection_name = collection_name or settings.QDRANT_BM25_COLLECTION
        self.vector_name = vector_name or settings.QDRANT_BM25_VECTOR_NAME
        self.prefer_grpc = prefer_grpc
        self._collection_ready = False

    # ---------------- collection 生命周期 ----------------
    async def ensure_collection(self) -> None:
        """确保 BM25 collection 存在：sparse-only + Modifier.IDF + payload 索引。幂等。"""

        client = await self._get_client()
        models = self._models()
        try:
            if not await client.collection_exists(collection_name=self.collection_name):
                # sparse-only collection：不配 dense vectors_config。
                await client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config={},
                    sparse_vectors_config={
                        self.vector_name: models.SparseVectorParams(
                            modifier=models.Modifier.IDF
                        )
                    },
                )
            if not self._collection_ready:
                # chunk_type 用 keyword（供 Formula match 与 filter）；租户/文档维度用 integer。
                await client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=PAYLOAD_CHUNK_TYPE,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                    wait=True,
                )
                for field_name in (PAYLOAD_USER_ID, PAYLOAD_DATASET_ID, PAYLOAD_DOC_ID):
                    await client.create_payload_index(
                        collection_name=self.collection_name,
                        field_name=field_name,
                        field_schema=models.PayloadSchemaType.INTEGER,
                        wait=True,
                    )
                self._collection_ready = True
        except Exception as exc:
            raise QdrantStoreError(
                f"Failed to ensure BM25 collection {self.collection_name}: {exc}"
            ) from exc

    # ---------------- 写入 ----------------
    async def upsert_chunks(self, points: Sequence[Bm25Point]) -> None:
        """按 chunk_id 幂等写入 BM25 sparse 向量 + payload。"""

        if not points:
            return
        client = await self._get_client()
        models = self._models()
        qdrant_points = [
            models.PointStruct(
                id=p.chunk_id,
                vector={
                    self.vector_name: models.SparseVector(
                        indices=p.sparse_vector.indices,
                        values=p.sparse_vector.values,
                    )
                },
                payload={
                    PAYLOAD_CHUNK_ID: p.chunk_id,
                    PAYLOAD_DOC_ID: p.doc_id,
                    PAYLOAD_USER_ID: p.user_id,
                    PAYLOAD_DATASET_ID: p.dataset_id,
                    PAYLOAD_CHUNK_TYPE: p.chunk_type,
                },
            )
            for p in points
        ]
        try:
            await client.upsert(
                collection_name=self.collection_name, points=qdrant_points, wait=True
            )
        except Exception as exc:
            raise QdrantStoreError(
                f"Failed to upsert BM25 points into {self.collection_name}: {exc}"
            ) from exc

    # ---------------- 查询（BM25 召回 + 乘法类型权重）----------------
    async def query(
        self,
        *,
        query_vector: EncodedSparseVector,
        user_id: int,
        dataset_id: int,
        doc_id: int | None,
        type_mult: Mapping[str, float],
        limit: int,
    ) -> list[Bm25ScoredPoint]:
        """BM25 sparse 召回 + Formula 乘法类型权重，多租户 filter 不计分。

        - ``type_mult`` 为空 → 纯 BM25：``query=SparseVector`` 直接召回。
        - ``type_mult`` 非空 → ``prefetch`` 召回 top-N 候选，再用 ``FormulaQuery``
          对候选重打分（``$score × 类型乘数``）。
        collection 不存在时返回空（等价于"无数据"，与写入侧解耦的合法中间态）。
        """

        if not query_vector.indices:
            return []

        client = await self._get_client()
        models = self._models()

        try:
            if not await client.collection_exists(collection_name=self.collection_name):
                logger.warning(
                    "[QdrantBm25Store.query] collection not found; empty hits: {}",
                    self.collection_name,
                )
                return []
        except Exception as exc:
            raise QdrantStoreError(
                f"Failed to check BM25 collection existence: {self.collection_name}: {exc}"
            ) from exc

        sparse = models.SparseVector(
            indices=query_vector.indices, values=query_vector.values
        )
        tenant = self._tenant_filter(models, user_id, dataset_id, doc_id)
        formula = self._build_formula(models, type_mult)

        try:
            if formula is None:
                response = await client.query_points(
                    collection_name=self.collection_name,
                    query=sparse,
                    using=self.vector_name,
                    query_filter=tenant,
                    limit=limit,
                    with_payload=True,
                    with_vectors=False,
                )
            else:
                prefetch_limit = max(limit, settings.BM25_PREFETCH_LIMIT)
                response = await client.query_points(
                    collection_name=self.collection_name,
                    prefetch=models.Prefetch(
                        query=sparse,
                        using=self.vector_name,
                        filter=tenant,
                        limit=prefetch_limit,
                    ),
                    query=formula,
                    limit=limit,
                    with_payload=True,
                    with_vectors=False,
                )
        except Exception as exc:
            raise QdrantStoreError(
                f"Failed to query BM25 collection {self.collection_name}: {exc}"
            ) from exc

        scored = getattr(response, "points", None) or []
        hits: list[Bm25ScoredPoint] = []
        for point in scored:
            payload = getattr(point, "payload", None) or {}
            chunk_id = payload.get(PAYLOAD_CHUNK_ID) or point.id
            doc_id_val = payload.get(PAYLOAD_DOC_ID)
            if chunk_id is None or doc_id_val is None:
                continue
            hits.append(
                Bm25ScoredPoint(
                    chunk_id=str(chunk_id),
                    doc_id=int(doc_id_val),
                    score=float(point.score),
                )
            )
        return hits

    # ---------------- 删除（文档级全量重建的删除半步）----------------
    async def delete_by_document(
        self, *, user_id: int, dataset_id: int, doc_id: int
    ) -> int:
        """按 user_id+dataset_id+doc_id 三维 filter 删除某文档的全部 chunk。

        与 ES delete_by_query 三维条件删除对齐，避免误删其他租户/文档。
        Qdrant delete 不返回命中数，统一返回 0（外层不消费该返回值）。
        """

        client = await self._get_client()
        models = self._models()
        try:
            if not await client.collection_exists(collection_name=self.collection_name):
                return 0
            await client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(
                    filter=self._tenant_filter(models, user_id, dataset_id, doc_id)
                ),
                wait=True,
            )
        except Exception as exc:
            if self._is_collection_missing_error(exc):
                return 0
            raise QdrantStoreError(
                f"Failed to delete BM25 document from {self.collection_name}: {exc}"
            ) from exc
        return 0

    async def point_exists(self, *, chunk_id: str) -> bool:
        """精确判断 BM25 独立 collection 中是否存在指定 chunk point。"""

        client = await self._get_client()
        try:
            if not await client.collection_exists(collection_name=self.collection_name):
                return False
            records = await client.retrieve(
                collection_name=self.collection_name,
                ids=[chunk_id],
                with_payload=False,
                with_vectors=False,
            )
        except Exception as exc:
            raise QdrantStoreError(
                f"Failed to check BM25 point existence in {self.collection_name}: {exc}"
            ) from exc
        return bool(records)

    @staticmethod
    def _is_collection_missing_error(exc: BaseException) -> bool:
        message = str(exc).lower()
        missing = any(
            marker in message
            for marker in ("not found", "does not exist", "doesn't exist", "missing")
        )
        return missing and "collection" in message

    async def close(self) -> None:
        """关闭本 store 自建的 client。"""

        if self._owns_client and self._client is not None and hasattr(self._client, "close"):
            await self._client.close()
            self._client = None

    # ---------------- 内部：filter / formula 构造 ----------------
    @staticmethod
    def _tenant_filter(models: Any, user_id: int, dataset_id: int, doc_id: int | None) -> Any:
        """多租户硬过滤（payload match，不参与打分）。"""

        must = [
            models.FieldCondition(key=PAYLOAD_USER_ID, match=models.MatchValue(value=user_id)),
            models.FieldCondition(
                key=PAYLOAD_DATASET_ID, match=models.MatchValue(value=dataset_id)
            ),
        ]
        if doc_id is not None:
            must.append(
                models.FieldCondition(key=PAYLOAD_DOC_ID, match=models.MatchValue(value=doc_id))
            )
        return models.Filter(must=must)

    @staticmethod
    def _build_formula(models: Any, type_mult: Mapping[str, float]) -> Any | None:
        """构造「$score × 类型乘数」的 FormulaQuery；type_mult 为空返回 None。

        类型乘数 = 1.0 + Σ (mult−1)·[chunk_type 命中]，即命中 heading(×1.3) 时
        乘数=1.3、未命中=1.0。Condition 在 formula 里求值为 1.0/0.0。
        """

        terms: list[Any] = [1.0]
        for chunk_type, mult in type_mult.items():
            delta = float(mult) - 1.0
            if delta == 0.0:
                continue
            terms.append(
                models.MultExpression(
                    mult=[
                        delta,
                        models.FieldCondition(
                            key=PAYLOAD_CHUNK_TYPE,
                            match=models.MatchValue(value=chunk_type),
                        ),
                    ]
                )
            )
        if len(terms) == 1:  # 没有任何有效乘数 → 退化为纯 BM25
            return None
        type_multiplier = models.SumExpression(sum=terms)
        return models.FormulaQuery(
            formula=models.MultExpression(mult=["$score", type_multiplier])
        )

    # ---------------- 内部：client ----------------
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

    @staticmethod
    def _client_class() -> Any:
        try:
            from qdrant_client import AsyncQdrantClient
        except ImportError as exc:
            raise QdrantVectorStorageConfigurationError(
                "qdrant-client is required to use QdrantBm25Store."
            ) from exc
        return AsyncQdrantClient

    @staticmethod
    def _models() -> Any:
        try:
            from qdrant_client import models
        except ImportError as exc:
            raise QdrantVectorStorageConfigurationError(
                "qdrant-client is required to use QdrantBm25Store."
            ) from exc
        return models
