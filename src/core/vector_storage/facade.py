"""提供向量存储模块对外统一调用入口。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from src.config import settings
from src.core.splitter.models import Chunk
from src.utils.logger import logger

from .compensation_pipeline import VectorStorageCompensationPipeline
from .exceptions import (
    VectorRetrievalBackendError,
    VectorRetrievalConfigurationError,
    VectorRetrievalEncodingError,
)
from .management_pipeline import VectorStorageManagementPipeline
from .models import (
    ChunkDeleteRequest,
    ChunkIndexingResult,
    ChunkMutationResult,
    ChunkStorageRequest,
    ChunkUpdateRequest,
    DenseVectorSearchRequest,
    SparseVectorSearchRequest,
    VectorSearchResult,
)
from .pipeline import VectorStoragePipeline

if TYPE_CHECKING:
    from src.core.sparse_vector import SparseVectorService
    from src.core.splitter.embedding_pipeline import ChunkEmbeddingPipeline


class VectorStorageFacade:
    """
    面向上游业务和调度器的向量存储统一入口。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(
        self,
        *,
        storage_service: VectorStoragePipeline,
        management_service: VectorStorageManagementPipeline,
        compensation_service: VectorStorageCompensationPipeline,
        qdrant_store: Any | None = None,
        sparse_vector_service: "SparseVectorService | None" = None,
        embedding_pipeline: "ChunkEmbeddingPipeline | None" = None,
    ) -> None:
        """
        初始化统一入口，并注入已经装配好的底层服务。

        Args:
            storage_service: 新增写入闭环服务。
            management_service: chunk 修改与删除管理服务。
            compensation_service: 失败与删除补偿服务。
            qdrant_store: 可选的 Qdrant 访问层，用于统一释放连接资源。
            sparse_vector_service: 可选的稀疏向量服务；用于召回入口
                ``search_sparse_chunks``。``SPARSE_VECTOR_ENABLED=False`` 时
                由工厂传入 ``None``，召回入口会抛 ``VectorRetrievalConfigurationError``。
            embedding_pipeline: 可选的 chunk embedding 管线；用于召回入口
                ``search_dense_chunks`` 调用 ``aembed_query`` 做 query 向量化。
                工厂始终注入；防御性 invariant 检查在 ``search_dense_chunks`` 内做。

        Returns:
            None.
        """
        self.storage_service = storage_service
        self.management_service = management_service
        self.compensation_service = compensation_service
        self.qdrant_store = qdrant_store
        # 命名前置 ``_`` 表达"内部状态"语义；外部不直接访问。
        self._sparse_vector_service = sparse_vector_service
        self._embedding_pipeline = embedding_pipeline

    async def store_chunks(
        self,
        *,
        user_id: int,
        set_id: int,
        doc_id: int,
        chunks: Sequence[Chunk],
    ) -> ChunkIndexingResult:
        """
        写入一批已经完成解析和切分的 chunk。

        Args:
            user_id: chunk 所属用户标识。
            set_id: chunk 所属知识集标识。
            doc_id: chunk 所属文档标识。
            chunks: 待写入和索引的 chunk 列表。

        Returns:
            ChunkIndexingResult: 本次写入闭环的处理结果。
        """
        return await self.storage_service.store_chunks(
            ChunkStorageRequest(
                user_id=user_id,
                set_id=set_id,
                doc_id=doc_id,
                chunks=list(chunks),
            )
        )

    async def index_chunks(
        self,
        *,
        user_id: int,
        set_id: int,
        doc_id: int,
        chunks: Sequence[Any],
    ) -> ChunkIndexingResult:
        """索引 pipeline 已过滤的 chunk 真值记录；调用方需提前剔除 ``dense_vector_status=SUCCESS``。

        替代旧版 ``index_document_chunks(include_failed=...)``：dense 模块不再按
        ``doc_id`` 自查 SQL、不感知首次/retry 场景；多值 CAS
        （``allowed_statuses=(PENDING, FAILED)``）在 SQL 层兜底，若现场过滤口径错误把
        已 SUCCESS chunk 混入，UPDATE 的 ``rowcount`` 不达预期会进失败路径。

        Args:
            user_id / set_id / doc_id: 业务归属（日志可读用途，写入主键由 chunk 自带）。
            chunks: pipeline 现场过滤好的待 dense 处理 chunk 真值（``ChunkRecordDB`` 行）。

        Returns:
            ChunkIndexingResult: 本次写入闭环的处理结果。
        """

        return await self.storage_service.index_chunks(
            user_id=user_id,
            set_id=set_id,
            doc_id=doc_id,
            chunks=chunks,
        )

    async def update_chunk(
        self,
        *,
        chunk_id: str,
        content: str,
        chunk_type: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        chunk_index: int | None = None,
    ) -> ChunkMutationResult:
        """
        修改单个 chunk 的真值内容，并在内容变化时重建对应向量。

        Args:
            chunk_id: 需要修改的 chunk 标识。
            content: 修改后的 chunk 文本。
            chunk_type: 可选的修改后 chunk 类型。
            start_line: 可选的修改后起始行号。
            end_line: 可选的修改后结束行号。
            chunk_index: 可选的修改后文档内顺序。

        Returns:
            ChunkMutationResult: 本次修改动作的处理结果。
        """
        return await self.management_service.update_chunk(
            ChunkUpdateRequest(
                chunk_id=chunk_id,
                content=content,
                chunk_type=chunk_type,
                start_line=start_line,
                end_line=end_line,
                chunk_index=chunk_index,
            )
        )

    async def delete_chunks(self, chunk_ids: Sequence[str]) -> ChunkMutationResult:
        """
        按 chunk_id 批量删除 chunk 的索引副本，并推进 MySQL 删除状态。

        Args:
            chunk_ids: 需要删除的 chunk 标识列表。

        Returns:
            ChunkMutationResult: 本次删除动作的处理结果。
        """
        return await self.management_service.delete_chunks(
            ChunkDeleteRequest(chunk_ids=list(chunk_ids))
        )

    async def retry_delete_failed(self, *, limit: int = 100) -> ChunkMutationResult:
        """
        执行一轮删除失败或删除中断记录恢复。

        Args:
            limit: 本轮最多处理的记录数。

        Returns:
            ChunkMutationResult: 删除补偿结果。
        """
        return await self.compensation_service.retry_delete_failed(limit=limit)

    async def repair_stale_indexing(self, *, limit: int = 100) -> ChunkMutationResult:
        """执行一轮卡住的 INDEXING 状态修复。"""
        return await self.compensation_service.repair_stale_indexing(limit=limit)

    async def mark_indexed_if_point_exists(
        self,
        chunk_ids: Sequence[str],
    ) -> ChunkMutationResult:
        """当 Qdrant point 已存在时，将对应 INDEXING 记录轻量修复为 INDEXED。"""
        return await self.compensation_service.mark_indexed_if_point_exists(chunk_ids)

    async def mark_failed_if_point_missing(
        self,
        chunk_ids: Sequence[str],
    ) -> ChunkMutationResult:
        """当 Qdrant point 确认不存在时，将对应 INDEXING 记录显式关闭为 FAILED。"""
        return await self.compensation_service.mark_failed_if_point_missing(chunk_ids)

    async def reindex_failed_chunks(self, chunk_ids: Sequence[str]) -> ChunkIndexingResult:
        """受控重建 FAILED chunk 的向量索引。"""
        return await self.compensation_service.reindex_failed_chunks(chunk_ids)

    async def search_sparse_chunks(
        self,
        *,
        query: str,
        user_id: int,
        set_id: int,
        doc_id: list[int] | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> VectorSearchResult:
        """基于 BGE-M3 稀疏向量在用户 / 知识集范围内召回最多 top-k 个 chunk。

        本方法是稀疏向量召回的**唯一对外入口**——内部把 query 走与写入链路同一份
        BGE-M3 服务向量化，再到对应 bucket collection 上做 named sparse vector search
        （vector name 与写入侧共用 ``settings.SPARSE_VECTOR_QDRANT_VECTOR_NAME``，
        默认 ``sparse_text``），命中通过 payload filter 限定到当前 user / set。

        **完全只读**：不动 MySQL ``sparse_vector_status``、不调 Qdrant
        ``upsert/update_vectors/delete``；同 query 多次调用结果稳定。

        Args:
            query: 用户问题或关键词；空字符串或全空白会**短路返空**，不调 encoder /
                Qdrant。
            user_id: 必填正整数；非法值抛 ``ValueError``。
            set_id: 必填正整数；非法值抛 ``ValueError``。
            doc_id: 可选 ``list[int]``。``None`` 或空列表不加 ``doc_id`` filter；
                非空列表用 Qdrant ``MatchAny`` 构造，支持"在若干文档内召回"。
            top_k: 可选；不传走 ``settings.SPARSE_RETRIEVAL_TOP_K``（默认 10）。
                合并后必须 ``> 0``，否则抛 ``ValueError``。
            score_threshold: 可选；不传走 ``settings.SPARSE_RETRIEVAL_SCORE_THRESHOLD``
                （默认 0.0）。合并后必须 ``>= 0``，否则抛 ``ValueError``。

        Returns:
            ``VectorSearchResult``：
            - ``hits`` 按 score 降序，长度 ``<= top_k``，全部满足 ``score >= threshold``。
            - 每个 hit 含 ``chunk_id`` / ``doc_id`` / ``set_id`` / ``score`` /
              ``vector_kind="sparse"``；**不含** ``content``——调用方拿到 ``chunk_id``
              后通过 ``ChunkRepository.get_by_chunk_ids`` 自行查 MySQL 回填真值。

        Raises:
            ValueError: 参数越界（``user_id`` / ``set_id`` / 合并后的 ``top_k`` /
                ``score_threshold``）。
            VectorRetrievalConfigurationError: ``SPARSE_VECTOR_ENABLED=False``、缺
                依赖、Qdrant URL 无效等部署侧问题。
            VectorRetrievalEncodingError: BGE-M3 推理失败。
            VectorRetrievalBackendError: Qdrant 网络故障 / 超时 / 服务不可用。
        """

        # 延迟运行时 import：sparse_vector 子包的异常类只在 facade 内部出现，
        # 调用方不需要 import；放到方法内可避免 facade 模块加载时强依赖
        # sparse_vector，方便 mypy / unit test 隔离。
        from src.core.qdrant_vector_storage.exceptions import (
            QdrantStoreError,
            QdrantVectorStorageConfigurationError,
        )
        from src.core.qdrant_vector_storage.models import SparseQueryVectorSpec
        from src.core.sparse_vector import (
            SparseVectorConfigurationError,
            SparseVectorError,
        )

        # ───────────────────── ① 参数越界校验（acceptance: 参数 Outline）─────────
        # 越界优先于"空 query 短路"——传错参数应当显式抛错，不该被静默吞掉。
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
            raise ValueError(f"user_id must be a positive integer, got {user_id!r}")
        if not isinstance(set_id, int) or isinstance(set_id, bool) or set_id <= 0:
            raise ValueError(f"set_id must be a positive integer, got {set_id!r}")
        effective_top_k = (
            top_k if top_k is not None else int(getattr(settings, "SPARSE_RETRIEVAL_TOP_K", 10))
        )
        effective_threshold = (
            score_threshold
            if score_threshold is not None
            else float(getattr(settings, "SPARSE_RETRIEVAL_SCORE_THRESHOLD", 0.0))
        )
        if (
            not isinstance(effective_top_k, int)
            or isinstance(effective_top_k, bool)
            or effective_top_k <= 0
        ):
            raise ValueError(f"top_k must be a positive integer, got {effective_top_k!r}")
        if effective_threshold < 0:
            raise ValueError(f"score_threshold must be >= 0, got {effective_threshold!r}")

        # 提前读取 vector_name：空 query / 配置错路径都需要它包装空 result。
        vector_name = self._sparse_vector_name()

        # ───────────────────── ② 空 query 短路（acceptance: 空 query Outline）──
        # 空字符串、全空白、控制字符（\t / \n 等）→ 直接返空；不调 encoder / Qdrant。
        # 召回链路常态化容错：上游字段填错时静默返空比抛 ValueError 安全。
        if not query or not query.strip():
            return VectorSearchResult(
                hits=[],
                vector_name=vector_name,
                top_k=effective_top_k,
                score_threshold=effective_threshold,
                model_name=None,
                vector_kind="sparse",
            )

        # ───────────────────── ③ 配置就绪检查 ───────────────────────────────────
        # SPARSE_VECTOR_ENABLED=False / 工厂未注入 service → 部署侧配置问题，
        # 静默返空会让运维找不到原因，必须显式抛配置异常（acceptance 已断言）。
        if (
            not bool(getattr(settings, "SPARSE_VECTOR_ENABLED", False))
            or self._sparse_vector_service is None
        ):
            raise VectorRetrievalConfigurationError(
                "Sparse vector recall is unavailable: "
                "SPARSE_VECTOR_ENABLED=False or sparse_vector_service is not configured."
            )

        # 内部 Request：仅作 facade → 内部底座的语义包装，不外暴；调用方走散参签名。
        _ = SparseVectorSearchRequest(
            query=query,
            user_id=user_id,
            set_id=set_id,
            doc_id=list(doc_id) if doc_id else None,
            top_k=effective_top_k,
            score_threshold=effective_threshold,
        )

        service = self._sparse_vector_service

        # ───────────────────── ④ query 向量化（异常翻译）─────────────────────────
        # 配置错优先（含依赖缺失），再降级为编码错；底层 SparseVectorOutputError
        # 已经是 SparseVectorError 子类，会被通用分支吞掉。
        try:
            sparse_vector = await service.vectorize_query(query)
        except SparseVectorConfigurationError as exc:
            raise VectorRetrievalConfigurationError(str(exc)) from exc
        except SparseVectorError as exc:  # 含 SparseVectorEncodingError / OutputError
            raise VectorRetrievalEncodingError(str(exc)) from exc

        if self.qdrant_store is None:
            # 工厂始终注入 qdrant_store；这里是防御性 invariant，避免 None.x。
            raise VectorRetrievalConfigurationError(
                "VectorStorageFacade requires qdrant_store to be configured for retrieval."
            )

        # ───────────────────── ⑤ bucket 路由（与写入侧共用 BucketRouter）────────
        bucket_route = self.qdrant_store.bucket_router.route_user(user_id)

        # ───────────────────── ⑥ 构造 query_vector_spec 与 payload_filter ────────
        query_spec = SparseQueryVectorSpec(
            vector_name=vector_name,
            indices=list(sparse_vector.indices),
            values=list(sparse_vector.values),
        )
        payload_filter = self._build_payload_filter(
            user_id=user_id,
            set_id=set_id,
            doc_id=doc_id,
        )

        # ───────────────────── ⑦ 调 store 底座（异常翻译）───────────────────────
        try:
            hits = await self.qdrant_store._search_chunks(
                bucket_id=bucket_route.bucket_id,
                query_vector_spec=query_spec,
                payload_filter=payload_filter,
                limit=effective_top_k,
                score_threshold=effective_threshold,
            )
        except QdrantVectorStorageConfigurationError as exc:
            raise VectorRetrievalConfigurationError(str(exc)) from exc
        except QdrantStoreError as exc:
            raise VectorRetrievalBackendError(str(exc)) from exc

        # ───────────────────── ⑧ 结果包装 ───────────────────────────────────────
        return VectorSearchResult(
            hits=hits,
            vector_name=vector_name,
            top_k=effective_top_k,
            score_threshold=effective_threshold,
            model_name=service.model_name,
            vector_kind="sparse",
        )

    async def search_dense_chunks(
        self,
        *,
        query: str,
        user_id: int,
        set_id: int,
        doc_id: list[int] | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> VectorSearchResult:
        """基于 system embedding 稠密向量在用户 / 知识集范围内召回最多 top-k 个 chunk。

        本方法是稠密向量召回的**唯一对外入口**——内部把 query 走与写入链路同一份
        ``ChunkEmbeddingPipeline`` 向量化（model 取 ``settings.SYSTEM_LLM_MODEL_EMBEDDING``，
        当前 ``text-embedding-v4``），再到对应 bucket collection 上做 unnamed
        dense vector search（写入侧 ``ensure_collection`` 用 ``vectors_config=
        VectorParams(size=1024, distance=COSINE)``，``PointStruct(vector=[...])`` 裸传），
        命中通过 payload filter 限定到当前 user / set。

        **完全只读**：不动 MySQL ``dense_vector_status``、不调 Qdrant
        ``upsert/update_vectors/delete``；同 query 多次调用结果稳定。

        本方法骨架与 ``search_sparse_chunks`` 共享，差异点：
        ① 段比 sparse 多一条 ``effective_threshold > 1.0`` 校验（cosine 上界 [0, 1]）
        ③ 段无 enable 检查（dense 写入是必备链路，无开关）
        ④ 段调 ``embedding_pipeline.aembed_query``（sparse 调
          ``sparse_vector_service.vectorize_query``）
        ⑥ 段构造 ``DenseQueryVectorSpec(vector=...)``（sparse 用
          ``SparseQueryVectorSpec(name, indices, values)``）
        ⑧ 段 ``vector_kind="dense"``，``vector_name=None`` 因为 unnamed，
          ``model_name=embedding_pipeline.embedding_model``

        修改本方法时必须同步审视 ``search_sparse_chunks``（brief §3.3.1 工程纪律）。

        Args:
            query: 用户问题或关键词；空字符串或全空白会**短路返空**，不调
                ``aembed_query`` / Qdrant。
            user_id: 必填正整数；非法值（含 ``bool`` 子类）抛 ``ValueError``。
            set_id: 必填正整数；非法值抛 ``ValueError``。
            doc_id: 可选 ``list[int]``。``None`` 或空列表不加 ``doc_id`` filter；
                非空列表用 Qdrant ``MatchAny`` 构造，支持"在若干文档内召回"。
            top_k: 可选；不传走 ``settings.DENSE_RETRIEVAL_TOP_K``（默认 10）。
                合并后必须 ``> 0``，否则抛 ``ValueError``。注意：pipeline 路径下
                实际 ``top_k`` 由 ``RECALL_RESULT_LIMIT`` 透传覆盖；
                ``DENSE_RETRIEVAL_TOP_K`` 仅作 facade 直调兜底。
            score_threshold: 可选；不传走
                ``settings.DENSE_RETRIEVAL_SCORE_THRESHOLD``（默认 0.0）。
                合并后必须 ``in [0, 1]``（cosine 上界），否则抛 ``ValueError``。

        Returns:
            ``VectorSearchResult``：
            - ``hits`` 按 score 降序，长度 ``<= top_k``，全部满足 ``score >= threshold``。
            - 每个 hit 含 ``chunk_id`` / ``doc_id`` / ``set_id`` / ``score`` /
              ``vector_kind="dense"``；**不含** ``content``——调用方拿到 ``chunk_id``
              后通过 ``ChunkRepository.list_by_chunk_ids`` 自行查 MySQL 回填真值，
              **并按 ``lifecycle_status == ACTIVE`` 过滤**消除删除间隙鬼影 hit
              （详见 TD §4.4.3 / §6.5）。

        Raises:
            ValueError: 参数越界（``user_id`` / ``set_id`` / 合并后的 ``top_k`` /
                ``score_threshold``）。
            VectorRetrievalConfigurationError: ``embedding_pipeline`` 或
                ``qdrant_store`` 未注入等部署侧问题。
            VectorRetrievalEncodingError: system embedding HTTP 推理失败。
            VectorRetrievalBackendError: Qdrant 网络故障 / 超时 / 服务不可用。
        """

        # 延迟运行时 import：qdrant_vector_storage 的异常类只在 facade 内部出现，
        # 调用方不需要 import；放到方法内可避免 facade 模块加载时强依赖
        # qdrant_vector_storage，方便 mypy / unit test 隔离。
        from src.core.qdrant_vector_storage.exceptions import (
            QdrantStoreError,
            QdrantVectorStorageConfigurationError,
        )
        from src.core.qdrant_vector_storage.models import DenseQueryVectorSpec

        # ───────────────────── ① 参数越界校验（与 sparse 几乎相同） ──────────────
        # 越界优先于"空 query 短路"——传错参数应当显式抛错，不该被静默吞掉。
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
            raise ValueError(f"user_id must be a positive integer, got {user_id!r}")
        if not isinstance(set_id, int) or isinstance(set_id, bool) or set_id <= 0:
            raise ValueError(f"set_id must be a positive integer, got {set_id!r}")
        effective_top_k = (
            top_k if top_k is not None else int(getattr(settings, "DENSE_RETRIEVAL_TOP_K", 10))
        )
        effective_threshold = (
            score_threshold
            if score_threshold is not None
            else float(getattr(settings, "DENSE_RETRIEVAL_SCORE_THRESHOLD", 0.0))
        )
        if (
            not isinstance(effective_top_k, int)
            or isinstance(effective_top_k, bool)
            or effective_top_k <= 0
        ):
            raise ValueError(f"top_k must be a positive integer, got {effective_top_k!r}")
        # dense 比 sparse 多一条 cosine 上界校验（§4.4.1 假设的代码层兜底）：
        # cosine 物理范围 [-1, 1]；本项目 score_threshold >= 0（"不过滤" = 0.0）；
        # > 1.0 会让 Qdrant 永远返 0 hits，调用方会误以为"没数据"。
        if effective_threshold < 0 or effective_threshold > 1.0:
            raise ValueError(
                f"score_threshold must be in [0, 1] (cosine bound), " f"got {effective_threshold!r}"
            )

        # ───────────────────── ② 空 query 短路（与 sparse 完全相同） ─────────────
        # 空字符串、全空白、控制字符（\t / \n 等）→ 直接返空；不调 aembed_query / Qdrant。
        # 召回链路常态化容错：上游字段填错时静默返空比抛 ValueError 安全。
        if not query or not query.strip():
            return VectorSearchResult(
                hits=[],
                vector_name=None,  # dense 是 unnamed vector
                top_k=effective_top_k,
                score_threshold=effective_threshold,
                model_name=None,
                vector_kind="dense",
            )

        # ───────────────────── ③ 配置就绪检查（dense 与 sparse 字面差异点）─────
        # dense 没有 enable 开关（dense 写入是必备链路）；只检查 embedding_pipeline /
        # qdrant_store 注入状态。两者都是工厂层 invariant；正常路径下不会触发。
        if self._embedding_pipeline is None:
            raise VectorRetrievalConfigurationError(
                "Dense vector recall is unavailable: " "embedding_pipeline is not configured."
            )
        if self.qdrant_store is None:
            raise VectorRetrievalConfigurationError(
                "VectorStorageFacade requires qdrant_store to be configured for retrieval."
            )

        # 内部 Request：仅作 facade → 内部底座的语义包装，不外暴；调用方走散参签名。
        _ = DenseVectorSearchRequest(
            query=query,
            user_id=user_id,
            set_id=set_id,
            doc_id=list(doc_id) if doc_id else None,
            top_k=effective_top_k,
            score_threshold=effective_threshold,
        )

        embedding_pipeline = self._embedding_pipeline

        # ───────────────────── ④ query 向量化（异常翻译，与 sparse 字面差异点）──
        # aembed_query 内部不翻译异常（参考 splitter/embedding_pipeline.py 实现）；
        # facade 在此处统一捕获并翻成 VectorRetrievalEncodingError。
        # ValueError（空 query / 长度不一致）属于 caller 错误，由 ① / ② 段已拦下，
        # 不到这里。
        try:
            dense_vector = await embedding_pipeline.aembed_query(query)
        except Exception as exc:
            # 包含 httpx.HTTPStatusError / httpx.TimeoutException / 其它远程错误。
            # ValueError 经 ① / ② 段后不会到这一步，但理论上仍会被吞——这是预期，
            # 防御性 invariant 失败时不漏到调用方意外手里。
            raise VectorRetrievalEncodingError(str(exc)) from exc

        # ───────────────────── ⑤ bucket 路由（与写入侧共用 BucketRouter）────────
        bucket_route = self.qdrant_store.bucket_router.route_user(user_id)

        # ───────────────────── ⑥ 构造 query_vector_spec 与 payload_filter ────────
        # spec 类型与 sparse 不同：dense 是 unnamed vector，spec 不带 vector_name。
        # payload_filter 完全复用 sparse 的 staticmethod（共用 _build_payload_filter）。
        query_spec = DenseQueryVectorSpec(vector=list(dense_vector))
        payload_filter = self._build_payload_filter(
            user_id=user_id,
            set_id=set_id,
            doc_id=doc_id,
        )

        # ───────────────────── ⑦ 调 store 底座（异常翻译，与 sparse 完全相同）──
        try:
            hits = await self.qdrant_store._search_chunks(
                bucket_id=bucket_route.bucket_id,
                query_vector_spec=query_spec,
                payload_filter=payload_filter,
                limit=effective_top_k,
                score_threshold=effective_threshold,
            )
        except QdrantVectorStorageConfigurationError as exc:
            raise VectorRetrievalConfigurationError(str(exc)) from exc
        except QdrantStoreError as exc:
            raise VectorRetrievalBackendError(str(exc)) from exc

        # ───────────────────── ⑧ 结果包装（dense 与 sparse 字面差异点）─────────
        # vector_kind="dense"；vector_name=None（unnamed vector）；
        # model_name 取自 embedding_pipeline 而非 sparse_vector_service。
        return VectorSearchResult(
            hits=hits,
            vector_name=None,
            top_k=effective_top_k,
            score_threshold=effective_threshold,
            model_name=embedding_pipeline.embedding_model,
            vector_kind="dense",
        )

    def _sparse_vector_name(self) -> str:
        """读取写入与召回共用的 sparse vector name；写读不分叉的同源点。

        优先取 service 上挂的 ``vector_name``（service 在工厂里就是从同一 settings
        字段读取的），降级到 settings 兜底。两条路径**不允许**返回不同的值。
        """

        if self._sparse_vector_service is not None:
            return self._sparse_vector_service.vector_name
        return str(getattr(settings, "SPARSE_VECTOR_QDRANT_VECTOR_NAME", "sparse_text"))

    @staticmethod
    def _build_payload_filter(
        *,
        user_id: int,
        set_id: int,
        doc_id: list[int] | None,
    ) -> Any:
        """构造 Qdrant payload filter；强制 must 包含 ``user_id`` + ``set_id``。

        ``doc_id`` 处理：``None`` 或空列表不加 filter；非空列表统一用 ``MatchAny``
        构造（即使单值也用列表传入），给"在若干文档内召回"留口子。
        """

        from qdrant_client import models

        must = [
            models.FieldCondition(
                key="user_id",
                match=models.MatchValue(value=user_id),
            ),
            models.FieldCondition(
                key="set_id",
                match=models.MatchValue(value=set_id),
            ),
        ]
        if doc_id:  # None 或 [] 都跳过；只有非空列表才追加 doc_id filter
            must.append(
                models.FieldCondition(
                    key="doc_id",
                    match=models.MatchAny(any=list(doc_id)),
                )
            )
        return models.Filter(must=must)

    async def close(self) -> None:
        """
        释放由门面持有的底层连接资源。

        Args:
            None.

        Returns:
            None.
        """
        if self.qdrant_store is not None and hasattr(self.qdrant_store, "close"):
            await self.qdrant_store.close()
