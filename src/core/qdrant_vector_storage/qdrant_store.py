from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from src.config import settings
from src.utils.logger import logger

from .bucket_router import BucketRouter
from .constants import (
    DEFAULT_BUCKET_COUNT,
    DEFAULT_COLLECTION_PREFIX,
    DEFAULT_QDRANT_TIMEOUT_SECONDS,
    QDRANT_PAYLOAD_INDEX_FIELDS,
)
from .exceptions import QdrantStoreError, QdrantVectorStorageConfigurationError
from .models import IndexedPoint, SparseIndexedPoint, SparseQueryVectorSpec

if TYPE_CHECKING:
    # 类型提示用：避免在运行时与 vector_storage 子包形成循环导入。
    # 运行时实现路径直接 import VectorSearchHit；vector_storage 已经依赖
    # qdrant_vector_storage（不是反向），所以反向 import 从设计上是安全的。
    from src.core.vector_storage.models import VectorSearchHit


class QdrantIndexStore:
    """封装 Qdrant bucket collection、dense point 和 sparse vector 的访问。"""

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
        """初始化 Qdrant 访问配置；测试可注入 fake client 和 bucket router。"""

        self._client = client
        self._owns_client = client is None
        self.bucket_router = bucket_router or BucketRouter(
            bucket_count=getattr(settings, "CHUNK_INDEX_BUCKET_COUNT", DEFAULT_BUCKET_COUNT),
            prefix=getattr(settings, "CHUNK_INDEX_COLLECTION_PREFIX", DEFAULT_COLLECTION_PREFIX),
        )
        self.host = host or settings.QDRANT_HOST
        self.port = port or settings.QDRANT_PORT
        resolved_api_key = (
            api_key if api_key is not None else getattr(settings, "QDRANT_API_KEY", None)
        )
        # 空串归一为 None：qdrant-client 见到非 None 的 api_key（含 ""）会强制 https，
        # 对明文 HTTP 部署触发 [SSL: WRONG_VERSION_NUMBER]。.env 里 QDRANT_API_KEY= 即空串。
        self.api_key = resolved_api_key or None
        self.timeout = timeout or getattr(
            settings,
            "QDRANT_TIMEOUT_SECONDS",
            DEFAULT_QDRANT_TIMEOUT_SECONDS,
        )
        self.prefer_grpc = prefer_grpc
        self._payload_index_ready_collections: set[str] = set()

    async def ensure_collection(self, *, bucket_id: int, vector_size: int) -> None:
        """确保 bucket collection 存在，并创建 dense 向量配置和 payload 索引。"""

        if vector_size <= 0:
            raise ValueError("vector_size must be positive.")

        client = await self._get_client()
        models = self._models()
        collection_name = self.bucket_router.collection_name(bucket_id)

        try:
            exists = await client.collection_exists(collection_name=collection_name)
            if not exists:
                # collection 必须在「创建时」就带 named sparse vector：Qdrant 不支持事后用
                # update_collection 给 dense-only collection 追加新的 named sparse vector
                # （返回 400 "Not existing vector name"）。dense 阶段先于 sparse 建表，
                # 若此处只建 dense，则 sparse 阶段 ensure_sparse_vector_schema 必然失败、
                # 稀疏索引永不可用。故按配置的 sparse 向量名把 collection 建成 hybrid-ready。
                sparse_vector_name = getattr(settings, "SPARSE_VECTOR_QDRANT_VECTOR_NAME", None)
                sparse_vectors_config = (
                    {sparse_vector_name: models.SparseVectorParams()}
                    if sparse_vector_name
                    else None
                )
                await client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                    ),
                    sparse_vectors_config=sparse_vectors_config,
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
        """按 chunk_id 幂等写入或覆盖 dense point。"""

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
            raise QdrantStoreError(
                f"Failed to upsert points into {collection_name}: {exc}"
            ) from exc

    async def ensure_sparse_vector_schema(self, *, bucket_id: int, vector_name: str) -> None:
        """确保 bucket collection 中存在指定 named sparse vector 配置。"""

        if not vector_name:
            raise ValueError("vector_name must not be empty.")

        client = await self._get_client()
        models = self._models()
        collection_name = self.bucket_router.collection_name(bucket_id)

        try:
            exists = await client.collection_exists(collection_name=collection_name)
            if not exists:
                raise QdrantStoreError(
                    f"Qdrant collection {collection_name} does not exist for sparse vector schema."
                )

            collection_info = await client.get_collection(collection_name=collection_name)
            sparse_names = self._collection_sparse_vector_names(collection_info)
            if vector_name in sparse_names:
                return

            await client.update_collection(
                collection_name=collection_name,
                sparse_vectors_config={vector_name: models.SparseVectorParams()},
            )
        except QdrantStoreError:
            raise
        except Exception as exc:
            raise QdrantStoreError(
                f"Failed to ensure sparse vector schema {vector_name} in {collection_name}: {exc}"
            ) from exc

    async def upsert_sparse_vectors(
        self,
        *,
        bucket_id: int,
        points: Sequence[SparseIndexedPoint],
    ) -> None:
        """把 sparse vector 追加到既有 point，避免覆盖同一 chunk 的 dense vector。"""

        if not points:
            return

        client = await self._get_client()
        models = self._models()
        collection_name = self.bucket_router.collection_name(bucket_id)
        qdrant_points = [
            models.PointVectors(
                id=point.chunk_id,
                vector={
                    point.vector_name: models.SparseVector(
                        indices=point.sparse_vector.indices,
                        values=point.sparse_vector.values,
                    )
                },
            )
            for point in points
        ]

        try:
            await client.update_vectors(
                collection_name=collection_name,
                points=qdrant_points,
                wait=True,
            )
        except Exception as exc:
            raise QdrantStoreError(
                f"Failed to upsert sparse vectors into {collection_name}: {exc}"
            ) from exc

    async def _search_chunks(
        self,
        *,
        bucket_id: int,
        query_vector_spec: SparseQueryVectorSpec,
        payload_filter: Any,
        limit: int,
        score_threshold: float,
    ) -> "list[VectorSearchHit]":
        """向量类型无关的搜索底座（私有，仅供 facade 调用）。

        ``_`` 前缀显式表达"模块内可见、不对业务方暴露"的语义边界。本方法只吞两类
        Qdrant SDK 异常并降级为空结果（业务等价于"没数据"）：
        - 目标 bucket collection 不存在
        - 目标 named sparse vector 在 collection 上未配置

        其他失败（网络、超时、配置缺失）一律抛 ``QdrantStoreError`` /
        ``QdrantVectorStorageConfigurationError``，由 facade 翻译为
        ``VectorRetrievalBackendError`` / ``VectorRetrievalConfigurationError``。

        D8 决议：store 层完成 ``ScoredPoint → VectorSearchHit`` 字段映射，facade
        不接触 qdrant-client 的 SDK 类型。本方法返回 ``list[VectorSearchHit]``。

        Args:
            bucket_id: 由 ``BucketRouter.route_user(user_id).bucket_id`` 计算得到的 bucket。
            query_vector_spec: 查询向量规格；本次只接受 ``SparseQueryVectorSpec``。
            payload_filter: ``models.Filter`` 实例（由 facade 构造，store 不感知字段语义）。
            limit: Qdrant ``query_points`` 的 limit；上层已做 ``> 0`` 校验。
            score_threshold: Qdrant ``query_points`` 的阈值；上层已做 ``>= 0`` 校验。

        Returns:
            按 score 降序的命中列表；命中数 <= limit。collection / named vector 不存在
            时返回 ``[]``。

        Raises:
            QdrantStoreError: Qdrant 网络 / 超时 / 服务不可用。
            QdrantVectorStorageConfigurationError: SDK 模块缺失等。
        """

        # 延迟运行时 import：避免与 vector_storage 子包形成模块加载期循环依赖。
        # vector_storage 在初始化时会 import qdrant_vector_storage（写入路径需要），
        # 反向只在 _search_chunks 实际被调用时拿到 VectorSearchHit 即可。
        from src.core.vector_storage.models import VectorSearchHit

        client = await self._get_client()
        models = self._models()
        collection_name = self.bucket_router.collection_name(bucket_id)

        # 容错点 1：collection 不存在 → 业务等价于"用户/set 没数据"，返空 + warn。
        # 与写入侧 ``delete_points`` 把"collection 不存在"当作合法语义一致。
        try:
            collection_present = await client.collection_exists(collection_name=collection_name)
        except Exception as exc:
            raise QdrantStoreError(
                f"Failed to check collection existence for search: {collection_name}: {exc}"
            ) from exc
        if not collection_present:
            logger.warning(
                "[QdrantIndexStore._search_chunks] collection not found; returning empty hits: "
                "bucket_id={} collection={}",
                bucket_id,
                collection_name,
            )
            return []

        # 构造 query 与 vector_kind：本次只支持 sparse；未来 dense / hybrid 增加分支。
        if isinstance(query_vector_spec, SparseQueryVectorSpec):
            query = models.SparseVector(
                indices=query_vector_spec.indices,
                values=query_vector_spec.values,
            )
            using = query_vector_spec.vector_name
            vector_kind = "sparse"
        else:  # pragma: no cover - 防御分支，dense / hybrid 接入时填充
            raise NotImplementedError(
                f"Unsupported query_vector_spec type: {type(query_vector_spec).__name__}"
            )

        # 容错点 2：named vector 不存在 → 写入侧尚未为该 collection 配置 sparse_text
        # schema 时返空；这是 dense-only 中间状态的合法常态。
        # 1.17.1 SDK 没有专属"named vector 不存在"异常类，只能在 except 内做关键词
        # 匹配；监听到典型关键词时降级为空集，否则透传为 QdrantStoreError。
        try:
            response = await client.query_points(
                collection_name=collection_name,
                query=query,
                using=using,
                query_filter=payload_filter,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            if self._is_named_vector_missing_error(exc):
                logger.warning(
                    "[QdrantIndexStore._search_chunks] named sparse vector not configured; "
                    "returning empty hits: bucket_id={} collection={} vector_name={}",
                    bucket_id,
                    collection_name,
                    using,
                )
                return []
            raise QdrantStoreError(f"Failed to query collection {collection_name}: {exc}") from exc

        # ScoredPoint → VectorSearchHit 字段映射；payload dict 在 store 层消化，
        # 不外泄给 facade 与调用方。score 已由 Qdrant 端按 limit / score_threshold
        # 过滤；本地不再二次过滤。
        scored_points = getattr(response, "points", None) or response  # 兼容老/新 API 形态
        hits: list[VectorSearchHit] = []
        for point in scored_points:
            payload = getattr(point, "payload", None) or {}
            hits.append(
                VectorSearchHit(
                    chunk_id=str(point.id),
                    doc_id=int(payload.get("doc_id", 0)),
                    set_id=int(payload.get("set_id", 0)),
                    score=float(point.score),
                    vector_kind=vector_kind,
                )
            )
        return hits

    @staticmethod
    def _is_named_vector_missing_error(exc: BaseException) -> bool:
        """识别"named vector 不存在"型底层异常，用于召回路径的语义降级。

        qdrant-client 1.17.1 没有专属异常类区分这种情况；这里同时尝试两类匹配，
        互为兜底：

        1. 异常本身或 ``__cause__`` 是 ``UnexpectedResponse``，且响应内容暗示
           "向量名不存在"。
        2. 关键词匹配（小写消息中含 "named vector"，或同时含 "vector" + "not found"，
           或同时含 "vector" + "does not exist"）。

        风险点：未来 SDK 升级可能改变错误消息文本；测试覆盖三类关键词组合，
        升级 SDK 时若行为退化会被打脸。
        """

        message = str(exc).lower()
        if "named vector" in message:
            return True
        if "not found" in message and ("vector" in message or "sparse" in message):
            return True
        if "does not exist" in message and ("vector" in message or "sparse" in message):
            return True
        return False

    async def point_exists(self, *, bucket_id: int, chunk_id: str) -> bool:
        """检查指定 chunk_id 对应的 Qdrant point 是否存在。"""

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
        """删除一批 chunk_id 对应的 Qdrant point。"""

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
            raise QdrantStoreError(
                f"Failed to delete points from {collection_name}: {exc}"
            ) from exc

    async def close(self) -> None:
        """关闭由本 store 自行创建的 Qdrant client。"""

        if self._owns_client and self._client is not None and hasattr(self._client, "close"):
            await self._client.close()
            self._client = None

    async def _get_client(self) -> Any:
        """懒创建并返回 Qdrant 异步客户端。"""

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

    def _collection_sparse_vector_names(self, collection_info: Any) -> set[str]:
        """从 Qdrant collection info 中提取已配置的 sparse vector 名称。"""

        params = getattr(getattr(collection_info, "config", None), "params", None)
        sparse_vectors = getattr(params, "sparse_vectors", None)
        if sparse_vectors is None and isinstance(params, dict):
            sparse_vectors = params.get("sparse_vectors")
        if sparse_vectors is None:
            return set()
        if isinstance(sparse_vectors, dict):
            return set(sparse_vectors.keys())
        return set(getattr(sparse_vectors, "keys", lambda: [])())

    def _client_class(self) -> Any:
        """延迟导入 qdrant-client 的异步客户端类。"""

        try:
            from qdrant_client import AsyncQdrantClient
        except ImportError as exc:
            raise QdrantVectorStorageConfigurationError(
                "qdrant-client is required to use QdrantIndexStore."
            ) from exc
        return AsyncQdrantClient

    def _models(self) -> Any:
        """延迟导入 qdrant-client models 命名空间。"""

        try:
            from qdrant_client import models
        except ImportError as exc:
            raise QdrantVectorStorageConfigurationError(
                "qdrant-client is required to use QdrantIndexStore."
            ) from exc
        return models
