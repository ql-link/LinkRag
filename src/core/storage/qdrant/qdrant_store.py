from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from src.config import settings
from src.utils.logger import logger

from .bucket_router import BucketRouter
from .constants import (
    DEFAULT_BUCKET_COUNT,
    DEFAULT_COLLECTION_PREFIX,
    DEFAULT_QDRANT_TIMEOUT_SECONDS,
    DEFAULT_QDRANT_WRITE_BACKOFF_SECONDS,
    DEFAULT_QDRANT_WRITE_MAX_ATTEMPTS,
    QDRANT_PAYLOAD_INDEX_FIELDS,
)
from .exceptions import QdrantStoreError, QdrantVectorStorageConfigurationError
from .models import (
    DenseQueryVectorSpec,
    IndexedPoint,
    SparseIndexedPoint,
    SparseQueryVectorSpec,
)

if TYPE_CHECKING:
    # 类型提示用：避免在运行时与 storage.vector 编排层形成循环导入。
    # 运行时实现路径直接 import VectorSearchHit；storage.vector 已经依赖
    # storage.qdrant（不是反向），所以反向 import 从设计上是安全的。
    from src.core.storage.vector.models import VectorSearchHit

_T = TypeVar("_T")

# 命中即判定为「瞬时网关/连接故障」的关键词（小写匹配）：共享 Qdrant 在并发写入下
# 偶发 502/503/504 网关错误与连接超时，重试即过。其余错误（4xx 校验、配置缺失）不重试。
_TRANSIENT_ERROR_MARKERS = (
    "502",
    "503",
    "504",
    "bad gateway",
    "service unavailable",
    "gateway time-out",
    "gateway timeout",
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "connection refused",
    "temporarily unavailable",
)


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

    @property
    def _dense_vector_name(self) -> str:
        """Qdrant named dense 向量字段名；写入与召回共用。"""
        return getattr(settings, "DENSE_VECTOR_QDRANT_VECTOR_NAME", "dense")

    @staticmethod
    def _is_transient_error(exc: BaseException) -> bool:
        """判断异常是否为可重试的瞬时网关/连接故障（502/503/504、超时、连接抖动）。

        qdrant-client 1.17.1 对网关 5xx 抛 ``UnexpectedResponse``（消息含状态码），
        底层 httpx/httpcore 超时与连接错误则各有类型。这里统一退到消息关键词匹配，
        既覆盖 ``UnexpectedResponse`` 也覆盖传输层异常，避免硬绑具体 SDK 类型。
        """
        message = str(exc).lower()
        if any(marker in message for marker in _TRANSIENT_ERROR_MARKERS):
            return True
        # 传输层异常往往 ``str(exc)`` 为空，补一层类名匹配兜底。
        type_name = type(exc).__name__.lower()
        return "timeout" in type_name or "connecterror" in type_name

    async def _with_write_retry(
        self, op_name: str, thunk: Callable[[], Awaitable[_T]]
    ) -> _T:
        """对幂等写操作做瞬时故障重试（指数退避）。

        ``thunk`` 必须幂等——本类所有写入都用显式 id 的 ``upsert`` / ``update_vectors``，
        重试不会产生重复或脏写。非瞬时错误立即透传，不浪费退避时间。
        """
        max_attempts = getattr(
            settings, "QDRANT_WRITE_MAX_ATTEMPTS", DEFAULT_QDRANT_WRITE_MAX_ATTEMPTS
        )
        backoff = getattr(
            settings, "QDRANT_WRITE_BACKOFF_SECONDS", DEFAULT_QDRANT_WRITE_BACKOFF_SECONDS
        )
        attempt = 0
        while True:
            try:
                return await thunk()
            except Exception as exc:
                attempt += 1
                if attempt >= max_attempts or not self._is_transient_error(exc):
                    raise
                delay = backoff * (2 ** (attempt - 1))
                logger.warning(
                    "[QdrantIndexStore] transient write failure on {}; retry {}/{} after {:.2f}s: {}",
                    op_name,
                    attempt,
                    max_attempts - 1,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

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
                # dense 为 named 向量（非匿名默认）：collection 无强制默认向量，因此可以
                # 先创建只含 payload 的点，dense / sparse 各自 update_vectors 独立写入。
                await self._with_write_retry(
                    "ensure_collection.create_collection",
                    lambda: client.create_collection(
                        collection_name=collection_name,
                        vectors_config={
                            self._dense_vector_name: models.VectorParams(
                                size=vector_size,
                                distance=models.Distance.COSINE,
                            )
                        },
                        sparse_vectors_config=sparse_vectors_config,
                    ),
                )

            if collection_name not in self._payload_index_ready_collections:
                for field_name in QDRANT_PAYLOAD_INDEX_FIELDS:
                    await self._with_write_retry(
                        "ensure_collection.create_payload_index",
                        lambda field_name=field_name: client.create_payload_index(
                            collection_name=collection_name,
                            field_name=field_name,
                            field_schema=models.PayloadSchemaType.INTEGER,
                            wait=True,
                        ),
                    )
                self._payload_index_ready_collections.add(collection_name)
        except Exception as exc:
            raise QdrantStoreError(
                f"Failed to ensure Qdrant collection {collection_name}: {exc}"
            ) from exc

    async def ensure_points(
        self, *, bucket_id: int, points: Sequence[IndexedPoint | SparseIndexedPoint]
    ) -> None:
        """确保给定 chunk 的 point 存在（只写 payload，不写任何向量）。

        create-if-missing 且幂等：先 retrieve 已存在的 id，只对缺失的 id upsert 一个
        ``vector={}`` 的空点。**绝不覆盖已存在点的向量**——这是 dense / sparse 能各自
        ``update_vectors`` 独立写入、互不影响的前提。并行 DAG 由专门的 ensure 步骤在
        dense / sparse 扇出前统一建点，避免二者并发建点相互覆盖。
        """
        if not points:
            return

        client = await self._get_client()
        models = self._models()
        collection_name = self.bucket_router.collection_name(bucket_id)

        ids = [point.chunk_id for point in points]
        try:
            existing = await self._with_write_retry(
                "ensure_points.retrieve",
                lambda: client.retrieve(
                    collection_name=collection_name,
                    ids=ids,
                    with_payload=False,
                    with_vectors=False,
                ),
            )
            existing_ids = {record.id for record in existing}
            missing = [point for point in points if point.chunk_id not in existing_ids]
            if not missing:
                return
            await self._with_write_retry(
                "ensure_points.upsert",
                lambda: client.upsert(
                    collection_name=collection_name,
                    points=[
                        models.PointStruct(id=point.chunk_id, vector={}, payload=point.payload)
                        for point in missing
                    ],
                    wait=True,
                ),
            )
        except Exception as exc:
            raise QdrantStoreError(
                f"Failed to ensure points in {collection_name}: {exc}"
            ) from exc

    async def upsert_points(self, *, bucket_id: int, points: Sequence[IndexedPoint]) -> None:
        """写入 dense named 向量到各 chunk 的 point（point 不存在则先建空点）。

        dense 为 named 向量，用 ``update_vectors`` 只更新 dense 维度，**不触碰 sparse**。
        因此 dense 与 sparse 谁先谁后、是否并发都互不覆盖。``ensure_points`` 保证 point
        已存在（``update_vectors`` 要求 point 存在）。
        """

        if not points:
            return

        await self.ensure_points(bucket_id=bucket_id, points=points)

        client = await self._get_client()
        models = self._models()
        collection_name = self.bucket_router.collection_name(bucket_id)
        dense_name = self._dense_vector_name
        qdrant_points = [
            models.PointVectors(id=point.chunk_id, vector={dense_name: point.vector})
            for point in points
        ]

        try:
            await self._with_write_retry(
                "upsert_points.update_vectors",
                lambda: client.update_vectors(
                    collection_name=collection_name,
                    points=qdrant_points,
                    wait=True,
                ),
            )
        except Exception as exc:
            raise QdrantStoreError(
                f"Failed to upsert dense vectors into {collection_name}: {exc}"
            ) from exc

    async def ensure_sparse_vector_schema(self, *, bucket_id: int, vector_name: str) -> None:
        """确保 bucket collection 中存在指定 named sparse vector 配置。"""

        if not vector_name:
            raise ValueError("vector_name must not be empty.")

        client = await self._get_client()
        models = self._models()
        collection_name = self.bucket_router.collection_name(bucket_id)

        try:
            exists = await self._with_write_retry(
                "ensure_sparse_vector_schema.collection_exists",
                lambda: client.collection_exists(collection_name=collection_name),
            )
            if not exists:
                raise QdrantStoreError(
                    f"Qdrant collection {collection_name} does not exist for sparse vector schema."
                )

            collection_info = await self._with_write_retry(
                "ensure_sparse_vector_schema.get_collection",
                lambda: client.get_collection(collection_name=collection_name),
            )
            sparse_names = self._collection_sparse_vector_names(collection_info)
            if vector_name in sparse_names:
                return

            await self._with_write_retry(
                "ensure_sparse_vector_schema.update_collection",
                lambda: client.update_collection(
                    collection_name=collection_name,
                    sparse_vectors_config={vector_name: models.SparseVectorParams()},
                ),
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
        """把 sparse named 向量写到各 chunk 的 point（point 不存在则先建空点）。

        用 ``update_vectors`` 只更新 sparse 维度，不触碰 dense；``ensure_points`` 保证
        point 已存在，使 sparse 不再依赖 dense 先建点——dense 与 sparse 可独立 / 并行写入。
        """

        if not points:
            return

        await self.ensure_points(bucket_id=bucket_id, points=points)

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
            await self._with_write_retry(
                "upsert_sparse_vectors.update_vectors",
                lambda: client.update_vectors(
                    collection_name=collection_name,
                    points=qdrant_points,
                    wait=True,
                ),
            )
        except Exception as exc:
            raise QdrantStoreError(
                f"Failed to upsert sparse vectors into {collection_name}: {exc}"
            ) from exc

    async def _search_chunks(
        self,
        *,
        bucket_id: int,
        query_vector_spec: SparseQueryVectorSpec | DenseQueryVectorSpec,
        payload_filter: Any,
        limit: int,
        score_threshold: float,
    ) -> "list[VectorSearchHit]":
        """向量类型无关的搜索底座（私有，仅供 facade 调用）。

        ``_`` 前缀显式表达"模块内可见、不对业务方暴露"的语义边界。本方法只吞两类
        Qdrant SDK 异常并降级为空结果（业务等价于"没数据"）：
        - 目标 bucket collection 不存在
        - 目标 named vector 在 collection 上未配置（常见于旧 collection 尚未迁移到
          named dense，或 sparse schema 未建成）

        其他失败（网络、超时、配置缺失）一律抛 ``QdrantStoreError`` /
        ``QdrantVectorStorageConfigurationError``，由 facade 翻译为
        ``VectorRetrievalBackendError`` / ``VectorRetrievalConfigurationError``。

        D8 决议：store 层完成 ``ScoredPoint → VectorSearchHit`` 字段映射，facade
        不接触 qdrant-client 的 SDK 类型。本方法返回 ``list[VectorSearchHit]``。

        Args:
            bucket_id: 由 ``BucketRouter.route_user(user_id).bucket_id`` 计算得到的 bucket。
            query_vector_spec: 查询向量规格；接受 ``SparseQueryVectorSpec`` /
                ``DenseQueryVectorSpec``（union dispatch）。
            payload_filter: ``models.Filter`` 实例（由 facade 构造，store 不感知字段语义）。
            limit: Qdrant ``query_points`` 的 limit；上层已做 ``> 0`` 校验。
            score_threshold: Qdrant ``query_points`` 的阈值；上层已做范围校验。

        Returns:
            按 score 降序的命中列表；命中数 <= limit。collection / named vector 不存在
            时返回 ``[]``。

        Raises:
            QdrantStoreError: Qdrant 网络 / 超时 / 服务不可用。
            QdrantVectorStorageConfigurationError: SDK 模块缺失等。
        """

        # 延迟运行时 import：避免与 storage.vector 编排层形成模块加载期循环依赖。
        # storage.vector 在初始化时会 import storage.qdrant（写入路径需要），
        # 反向只在 _search_chunks 实际被调用时拿到 VectorSearchHit 即可。
        from src.core.storage.vector.models import VectorSearchHit

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

        # 构造 query 与 vector_kind：sparse 分支由 sparse-vector-recall 阶段引入；
        # 本期（dense-vector-recall）补 dense 分支。hybrid 接入时再加 elif。
        vector_kind: Literal["sparse", "dense"]
        if isinstance(query_vector_spec, SparseQueryVectorSpec):
            query = models.SparseVector(
                indices=query_vector_spec.indices,
                values=query_vector_spec.values,
            )
            using = query_vector_spec.vector_name
            vector_kind = "sparse"
        elif isinstance(query_vector_spec, DenseQueryVectorSpec):
            # dense 是 named vector：写入侧 ``ensure_collection`` 用
            # ``vectors_config={dense_name: VectorParams(...)}``，写入用
            # ``update_vectors({dense_name: [...]})``；召回侧 ``using=dense_name``，
            # ``query`` 直接给 list[float]。
            query = list(query_vector_spec.vector)
            using = self._dense_vector_name
            vector_kind = "dense"
        else:  # pragma: no cover - 防御分支，hybrid 接入时填充
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
        # 兼容老/新 API 形态：新版返回带 ``points`` 字段的响应对象，老版直接可迭代。
        # 注意用 ``is not None`` 而非 ``or``——``points`` 为空 list（阈值过滤后零命中）时
        # ``[] or response`` 会错误回退去迭代 response 自身、产出 (字段名, 值) 元组导致
        # ``'tuple' object has no attribute 'id'``。空 list 是合法的"零命中"，应原样使用。
        points = getattr(response, "points", None)
        scored_points = points if points is not None else response
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
        if "doesn't exist" in message and ("vector" in message or "sparse" in message):
            return True
        if "not existing" in message and ("vector" in message or "sparse" in message):
            return True
        if "not configured" in message and ("vector" in message or "sparse" in message):
            return True
        return False

    async def get_named_vector_presence(
        self,
        *,
        bucket_id: int,
        chunk_ids: Sequence[str],
        vector_name: str,
    ) -> dict[str, bool]:
        """逐 chunk 判断指定 named vector 是否真实存在。

        这里不能复用 :meth:`point_exists`：解析 DAG 会先创建只有 payload 的空 point，
        因此 point 存在并不能证明 dense / sparse 任一路已经写入成功。返回值始终包含
        所有传入的 chunk_id；collection、named-vector schema 或具体 point 不存在时，
        对应结果均为 ``False``。
        """

        presence = {str(chunk_id): False for chunk_id in chunk_ids}
        if not presence:
            return presence
        if not vector_name:
            raise ValueError("vector_name must not be empty.")

        client = await self._get_client()
        collection_name = self.bucket_router.collection_name(bucket_id)

        try:
            exists = await client.collection_exists(collection_name=collection_name)
            if not exists:
                return presence
            records = await client.retrieve(
                collection_name=collection_name,
                ids=list(presence),
                with_payload=False,
                with_vectors=[vector_name],
            )
        except Exception as exc:
            # 老 collection 尚未配置该 named vector 是合法中间态，等价于全量缺失。
            if (
                self._is_named_vector_missing_error(exc)
                or self._is_collection_or_point_missing_error(exc)
            ):
                return presence
            raise QdrantStoreError(
                f"Failed to inspect named vector {vector_name!r} in {collection_name}: {exc}"
            ) from exc

        for record in records:
            chunk_id = str(record.id)
            if chunk_id not in presence:
                continue
            vectors = getattr(record, "vector", None)
            presence[chunk_id] = isinstance(vectors, Mapping) and vector_name in vectors
        return presence

    async def delete_named_vectors(
        self,
        *,
        bucket_id: int,
        chunk_ids: Sequence[str],
        vector_name: str,
    ) -> None:
        """仅删除一批 point 上的目标 named vector，保留 payload 与 sibling vectors。

        该操作供索引补偿使用，必须保持幂等：collection、point 或 named vector 已经
        不存在均视为清理成功。Qdrant 的 ``delete_vectors`` 对缺失 point/vector 本身
        是幂等的；这里另行吞掉 schema 或 collection 在检查后被删除的竞态错误。
        """

        if not chunk_ids:
            return
        if not vector_name:
            raise ValueError("vector_name must not be empty.")

        client = await self._get_client()
        collection_name = self.bucket_router.collection_name(bucket_id)

        try:
            exists = await client.collection_exists(collection_name=collection_name)
            if not exists:
                return
            await self._with_write_retry(
                "delete_named_vectors.delete_vectors",
                lambda: client.delete_vectors(
                    collection_name=collection_name,
                    vectors=[vector_name],
                    points=list(chunk_ids),
                    wait=True,
                ),
            )
        except Exception as exc:
            if (
                self._is_named_vector_missing_error(exc)
                or self._is_collection_or_point_missing_error(exc)
            ):
                return
            raise QdrantStoreError(
                f"Failed to delete named vector {vector_name!r} from {collection_name}: {exc}"
            ) from exc

    @staticmethod
    def _is_collection_or_point_missing_error(exc: BaseException) -> bool:
        """识别读写间 collection / point 已不存在的幂等语义。"""

        message = str(exc).lower()
        missing_marker = any(
            marker in message
            for marker in (
                "not found",
                "does not exist",
                "doesn't exist",
                "not existing",
                "missing",
                "no point with id",
            )
        )
        return missing_marker and ("collection" in message or "point" in message)

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
