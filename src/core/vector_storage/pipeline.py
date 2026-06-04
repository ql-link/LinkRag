"""编排分片真值持久化、向量化与 Qdrant 索引写入。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.core.chunk_fact_storage import ChunkRepository
from src.core.chunk_fact_storage.constants import (
    CHUNK_LIFECYCLE_ACTIVE,
    CHUNK_STATUS_FAILED,
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_INDEXING,
    CHUNK_STATUS_PENDING,
    SPARSE_VECTOR_STATUS_FAILED,
    SPARSE_VECTOR_STATUS_INDEXING,
    SPARSE_VECTOR_STATUS_PENDING,
)
from src.core.qdrant_vector_storage import IndexedPoint, QdrantIndexStore
from src.core.qdrant_vector_storage.point_factory import (
    chunk_from_record,
    indexed_point_from_record,
    sparse_indexed_point_from_record,
)
from src.core.sparse_vector import SparseChunkVectorizationRequest, SparseVectorService
from src.core.splitter.embedding_pipeline import ChunkEmbeddingPipeline
from src.core.splitter.factory import (
    DenseEmbeddingDimensionError,
    aresolve_user_chunk_embedding_pipeline,
    validate_dense_dimension,
)
from src.utils.logger import logger

from ._transaction import TransactionalPipelineMixin
from .draft_factory import ChunkDraftFactory
from .models import (
    ChunkIndexingResult,
    ChunkStorageRequest,
    VectorBranch,
    VectorCompensationEntry,
    VectorFailureStep,
)


class _VectorBranchFailure(RuntimeError):
    """Internal exception carrying branch and failed-step metadata."""

    def __init__(
        self,
        message: str,
        *,
        branch: VectorBranch,
        step: VectorFailureStep,
        chunk_id: str,
    ) -> None:
        super().__init__(message)
        self.branch = branch
        self.step = step
        self.chunk_id = chunk_id


class VectorStoragePipeline(TransactionalPipelineMixin):
    """
        编排 chunk 真值入库、embedding、Qdrant 建索引与状态回写的主服务入口。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        draft_factory: ChunkDraftFactory,
        repository: ChunkRepository,
        qdrant_store: QdrantIndexStore,
        embedding_pipeline: ChunkEmbeddingPipeline,
        sparse_vector_service: SparseVectorService | None = None,
        retry_limit: int | None = None,
        retry_interval_seconds: int | None = None,
        max_inline_retry_sleep_seconds: int = 5,
    ) -> None:
        """
            初始化主写入服务，并注入事务工厂、仓储、向量索引与 embedding 依赖。

        Args:
            session_factory: 负责创建异步数据库会话的 session 工厂。
            draft_factory: 负责把 Chunk 转换为存储草稿的工厂对象。
            repository: MySQL 真值表仓储。
            qdrant_store: Qdrant 索引访问层。
            embedding_pipeline: 负责 chunk 向量化的 embedding 管线。

        Returns:
            None.
        """
        self.session_factory = session_factory
        self.draft_factory = draft_factory
        self.repository = repository
        self.qdrant_store = qdrant_store
        self.embedding_pipeline = embedding_pipeline
        self.sparse_vector_service = sparse_vector_service
        self.retry_limit = max(
            0,
            (
                retry_limit
                if retry_limit is not None
                else getattr(settings, "CHUNK_INDEX_RETRY_LIMIT", 0)
            ),
        )
        self.retry_interval_seconds = max(
            0,
            (
                retry_interval_seconds
                if retry_interval_seconds is not None
                else getattr(settings, "CHUNK_INDEX_RETRY_INTERVAL_SECONDS", 0)
            ),
        )
        self.max_inline_retry_sleep_seconds = max(0, max_inline_retry_sleep_seconds)

    async def store_chunks(
        self,
        request: ChunkStorageRequest,
    ) -> ChunkIndexingResult:
        """
            兼容旧入口：按 ``doc_id`` 反查已落库 chunk 真值后委托给 ``index_chunks``；
            不再执行 chunk 真值 INSERT。

        Args:
            request: 包含业务上下文的存储请求；其中的 ``chunks`` 字段在新边界下被忽略，
                索引依据来自已落库真值。

        Returns:
            ChunkIndexingResult: 本次写入任务的结果汇总。
        """

        # 把"按 doc_id 反查 + 现场过滤"收敛进这里，让 ``index_chunks`` 唯一对外。
        async with self.session_factory() as session:
            stmt = (
                select(self.repository.model_cls)
                .where(self.repository.model_cls.doc_id == request.doc_id)
                .where(self.repository.model_cls.lifecycle_status == CHUNK_LIFECYCLE_ACTIVE)
                .order_by(self.repository.model_cls.chunk_index.asc())
            )
            result = await session.execute(stmt)
            records = list(result.scalars().all())

        # 现场过滤：仅保留待 dense 处理的 chunk（与 pipeline 现场过滤口径一致）。
        dense_chunks = [r for r in records if r.dense_vector_status != CHUNK_STATUS_INDEXED]

        return await self.index_chunks(
            user_id=request.user_id,
            set_id=request.set_id,
            doc_id=request.doc_id,
            chunks=dense_chunks,
        )

    async def index_chunks(
        self,
        *,
        user_id: int,
        set_id: int,
        doc_id: int,
        chunks: Sequence[object],
    ) -> ChunkIndexingResult:
        """以 batch 为单位向量化并写入向量索引副本；调用方需提供已过滤的 chunks。

        与被替换的旧 ``index_document_chunks`` 相比，本入口：

        * 不再按 ``doc_id`` 反查 SQL —— chunks 由 pipeline 现场过滤后透传。
        * 单条 SQL 多值 CAS（``allowed_statuses=(PENDING, FAILED)``）覆盖两种合法旧态，
          替代旧版 ``_group_records_by_dense_status`` 分组多次 UPDATE 的写法。
        * ``total_chunks`` 等于 ``len(chunks)``——不再做"全文档已完成数"折算。

        以 batch_size 为单位逐批处理：每批 embed 成功后立即写入 Qdrant 并 mark_indexed，
        某批失败则将该批标记 FAILED 并停止，后续批次保持 PENDING / INDEXING 等待补偿路径重试。
        这样已成功的 batch 不会因后续 batch 失败而重复 embed，同时整篇文章的
        pipeline_status 因存在失败 chunk 而保持 FAILED，搜索路径不会触达部分入库的文章。

        Args:
            user_id / set_id / doc_id: 业务归属，仅日志可读用途；写入主键由 chunk 自带。
            chunks: pipeline 现场过滤好的待 dense 处理 chunk 真值序列（``ChunkRecordDB`` 行）。
        """

        # set_id / doc_id 仅作日志可读，dense 写入主键由 chunk 自带；user_id 用于解析
        # 发起用户的稠密 embedder（LINK-91）。
        _ = (set_id, doc_id)

        records = list(chunks)

        # 空集短路：调用方现场过滤后没有待处理 chunk，等价于成功。
        if not records:
            return ChunkIndexingResult(total_chunks=0, indexed_chunks=0)

        # 方案 A：写入链路按发起用户解析稠密 embedder（必配 EMBEDDING、无系统兜底）。
        # 配置缺失（DenseEmbeddingConfigMissingError）在此直接向上抛出，不触碰任何 chunk
        # 状态，由 VectorizingStage 归类为 LLM_CONFIG_MISSING 并通知 Java，而不是被下方
        # batch 失败路径吞成 generic VECTORIZING_FAILED。
        embedding_pipeline = await aresolve_user_chunk_embedding_pipeline(user_id)

        embedding_model: str | None = None
        indexed_count = 0
        batch_size = embedding_pipeline.batch_size

        # ── 以 batch 为单位逐批处理 ────────────────────────────────────────
        # 每批：mark_indexing → embed → 写 Qdrant → mark_indexed
        # 某批 mark_indexing rowcount 不达预期 → 该批走失败路径，停止后续 batch
        # 某批 embed 失败 → 该批标 FAILED，停止
        # 单 chunk 写入失败 → 当前 chunk 标 FAILED，同批后续 chunk 保持 INDEXING
        for batch_start in range(0, len(records), batch_size):
            batch_records = records[batch_start : batch_start + batch_size]
            batch_chunk_ids = [str(getattr(r, "chunk_id")) for r in batch_records]

            # 1. 批量 mark_indexing：多值 CAS 拦下混入的 SUCCESS / INDEXING chunk。
            try:
                indexing_count = await self._mark_indexing(
                    batch_chunk_ids,
                    embedding_model=None,
                    allowed_statuses=(CHUNK_STATUS_PENDING, CHUNK_STATUS_FAILED),
                )
                if indexing_count != len(batch_chunk_ids):
                    raise RuntimeError(
                        "Skipped dense indexing because rowcount "
                        f"{indexing_count} != {len(batch_chunk_ids)} "
                        "(some chunks not in (PENDING, FAILED))."
                    )
            except Exception as exc:
                compensation_entry = await self._safe_mark_branch_failed(
                    batch_records[0],
                    branch=VectorBranch.DENSE,
                    step=VectorFailureStep.SQL_STATUS_WRITE,
                    error_msg=str(exc),
                )
                logger.exception(
                    "[VectorStoragePipeline] Batch mark_indexing failed at batch_start={}: {}",
                    batch_start,
                    exc,
                )
                return ChunkIndexingResult(
                    total_chunks=len(records),
                    indexed_chunks=indexed_count,
                    failed_chunk_ids=[batch_chunk_ids[0]],
                    embedding_model=embedding_model,
                    compensation_entry=compensation_entry,
                )

            # 2. 批量 embed
            try:
                batch_chunks = [chunk_from_record(r) for r in batch_records]
                embedded_batch = await embedding_pipeline.aembed_chunks(batch_chunks)
                if len(embedded_batch) != len(batch_records):
                    raise ValueError(
                        f"Embedded chunk count mismatch: got {len(embedded_batch)}, "
                        f"expected {len(batch_records)}."
                    )
                # 方案 A 维度校验：用户模型输出维度必须等于系统统一维度，否则写入共享
                # collection 必然冲突。维度不符是「配错模型」而非瞬时故障，故标失败后向上抛出，
                # 不进补偿重试。校验逻辑与补偿重建链路共用 ``validate_dense_dimension``。
                validate_dense_dimension(
                    embedded_batch,
                    user_id=user_id,
                    model_name=embedding_pipeline.embedding_model,
                )
            except DenseEmbeddingDimensionError:
                await self._safe_mark_failed(batch_chunk_ids, "EMBEDDING_DIMENSION_UNSUPPORTED")
                raise
            except Exception as exc:
                await self._safe_mark_failed(batch_chunk_ids, str(exc))
                compensation_entry = VectorCompensationEntry(
                    document_id=int(getattr(batch_records[0], "doc_id")),
                    chunk_id=batch_chunk_ids[0],
                    vector_branch=VectorBranch.DENSE,
                    failed_step=VectorFailureStep.VECTOR_GENERATION,
                )
                logger.exception(
                    "[VectorStoragePipeline] Batch embedding failed at batch_start={}: {}",
                    batch_start,
                    exc,
                )
                return ChunkIndexingResult(
                    total_chunks=len(records),
                    indexed_chunks=indexed_count,
                    failed_chunk_ids=batch_chunk_ids,
                    embedding_model=embedding_model,
                    compensation_entry=compensation_entry,
                )

            embedding_model = self._resolve_embedding_model(
                embedded_batch, pipeline=embedding_pipeline
            )

            # 3. 逐条写入 Qdrant + mark_indexed
            # 写入阶段遇到失败立即停止（该 chunk 标 FAILED），
            # 同批后续 chunk 已有向量但不写入，保持 PENDING 等待下次重试。
            for record, embedded in zip(batch_records, embedded_batch):
                chunk_id = str(getattr(record, "chunk_id"))
                try:
                    point = indexed_point_from_record(record, embedded)
                    await self._ensure_and_upsert([point])
                except Exception as exc:
                    compensation_entry = await self._safe_mark_branch_failed(
                        record,
                        branch=VectorBranch.DENSE,
                        step=VectorFailureStep.INDEX_WRITE,
                        error_msg=str(exc),
                    )
                    logger.exception(
                        "[VectorStoragePipeline] Qdrant upsert failed for chunk {}: {}",
                        chunk_id,
                        exc,
                    )
                    return ChunkIndexingResult(
                        total_chunks=len(records),
                        indexed_chunks=indexed_count,
                        failed_chunk_ids=[chunk_id],
                        embedding_model=embedding_model,
                        compensation_entry=compensation_entry,
                    )

                try:
                    indexed_count_result = await self._mark_indexed(
                        [chunk_id], embedding_model=embedding_model
                    )
                    if indexed_count_result != 1:
                        raise RuntimeError(
                            f"Skipped stale dense index completion because rowcount "
                            f"{indexed_count_result} != 1 for chunk {chunk_id}."
                        )
                except Exception as exc:
                    compensation_entry = await self._safe_mark_branch_failed(
                        record,
                        branch=VectorBranch.DENSE,
                        step=VectorFailureStep.SQL_STATUS_WRITE,
                        error_msg=str(exc),
                    )
                    logger.exception(
                        "[VectorStoragePipeline] mark_indexed failed for chunk {}: {}",
                        chunk_id,
                        exc,
                    )
                    return ChunkIndexingResult(
                        total_chunks=len(records),
                        indexed_chunks=indexed_count,
                        failed_chunk_ids=[chunk_id],
                        embedding_model=embedding_model,
                        compensation_entry=compensation_entry,
                    )

                indexed_count += 1

        return ChunkIndexingResult(
            total_chunks=len(records),
            indexed_chunks=indexed_count,
            embedding_model=embedding_model,
        )

    async def _index_record_with_retry(self, record: object) -> ChunkIndexingResult:
        """对单条 SQL chunk 记录执行 `dense -> sparse` 串行索引，失败只重试当前分支。"""

        needs_dense = self._needs_dense(record)
        needs_sparse = self._needs_sparse(record)
        dense_done = not needs_dense
        sparse_done = not needs_sparse
        dense_indexing_marked = False
        sparse_indexing_marked = False
        embedding_model: str | None = None
        sparse_model: str | None = None
        last_error: _VectorBranchFailure | None = None

        for attempt in range(self.retry_limit + 1):
            try:
                if not dense_done:
                    embedding_model = await self._index_dense_branch(
                        record,
                        mark_indexing=not dense_indexing_marked,
                    )
                    dense_done = True
                if not sparse_done:
                    sparse_model = await self._index_sparse_branch(
                        record,
                        mark_indexing=not sparse_indexing_marked,
                    )
                    sparse_done = True
                return ChunkIndexingResult(
                    total_chunks=1,
                    indexed_chunks=1,
                    embedding_model=embedding_model,
                    sparse_model=sparse_model,
                )
            except _VectorBranchFailure as exc:
                last_error = exc
                if (
                    exc.branch == VectorBranch.DENSE
                    and exc.step != VectorFailureStep.SQL_STATUS_WRITE
                ):
                    dense_indexing_marked = True
                if (
                    exc.branch == VectorBranch.SPARSE
                    and exc.step != VectorFailureStep.SQL_STATUS_WRITE
                ):
                    sparse_indexing_marked = True
                if attempt >= self.retry_limit:
                    break

                sleep_seconds = self._retry_sleep_seconds()
                logger.warning(
                    "[VectorStoragePipeline] Chunk indexing failed, retrying: "
                    f"chunk_id={exc.chunk_id}, branch={exc.branch.value}, "
                    f"attempt={attempt + 1}/{self.retry_limit + 1}, "
                    f"sleep_seconds={sleep_seconds}, error={exc}"
                )
                if sleep_seconds > 0:
                    await asyncio.sleep(sleep_seconds)

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"unknown chunk indexing failure for {getattr(record, 'chunk_id', '')}")

    async def _index_dense_branch(
        self,
        record: object,
        *,
        mark_indexing: bool,
    ) -> str | None:
        """执行单 chunk dense 分支：状态切换、embedding、Qdrant 写入、SQL 确认。"""

        chunk_id = str(getattr(record, "chunk_id"))
        if mark_indexing:
            try:
                indexing_count = await self._mark_indexing(
                    [chunk_id],
                    embedding_model=None,
                    allowed_statuses=(str(getattr(record, "dense_vector_status")),),
                )
                if indexing_count != 1:
                    raise RuntimeError(
                        "Skipped dense indexing because rowcount "
                        f"{indexing_count} != 1 for chunk {chunk_id}."
                    )
            except Exception as exc:
                raise self._branch_failure(
                    exc,
                    branch=VectorBranch.DENSE,
                    step=VectorFailureStep.SQL_STATUS_WRITE,
                    chunk_id=chunk_id,
                ) from exc

        try:
            embedded_chunks = await self.embedding_pipeline.aembed_chunks(
                [chunk_from_record(record)]
            )
            if len(embedded_chunks) != 1:
                raise ValueError(
                    "Embedded chunk count does not match current chunk: "
                    f"{len(embedded_chunks)} != 1 for chunk {chunk_id}."
                )
        except Exception as exc:
            raise self._branch_failure(
                exc,
                branch=VectorBranch.DENSE,
                step=VectorFailureStep.VECTOR_GENERATION,
                chunk_id=chunk_id,
            ) from exc

        embedding_model = self._resolve_embedding_model(embedded_chunks)
        try:
            point = indexed_point_from_record(record, embedded_chunks[0])
            await self._ensure_and_upsert([point])
        except Exception as exc:
            raise self._branch_failure(
                exc,
                branch=VectorBranch.DENSE,
                step=VectorFailureStep.INDEX_WRITE,
                chunk_id=chunk_id,
            ) from exc

        try:
            indexed_count = await self._mark_indexed([chunk_id], embedding_model=embedding_model)
            if indexed_count != 1:
                raise RuntimeError(
                    "Skipped stale dense index completion because rowcount "
                    f"{indexed_count} != 1 for chunk {chunk_id}."
                )
        except Exception as exc:
            raise self._branch_failure(
                exc,
                branch=VectorBranch.DENSE,
                step=VectorFailureStep.SQL_STATUS_WRITE,
                chunk_id=chunk_id,
            ) from exc

        return embedding_model

    async def _index_sparse_branch(
        self,
        record: object,
        *,
        mark_indexing: bool,
    ) -> str | None:
        """执行单 chunk sparse 分支，必须在 dense 已成功或已跳过后调用。"""

        if not self._sparse_enabled():
            return None
        if self.sparse_vector_service is None:
            raise RuntimeError(
                "SPARSE_VECTOR_ENABLED=true but sparse vector service is not configured."
            )

        chunk_id = str(getattr(record, "chunk_id"))
        model_name = self._sparse_model_name()
        if mark_indexing:
            try:
                indexing_count = await self._mark_sparse_indexing(
                    [chunk_id],
                    model_name=model_name,
                    allowed_statuses=(str(getattr(record, "sparse_vector_status")),),
                )
                if indexing_count != 1:
                    raise RuntimeError(
                        "Skipped sparse indexing because rowcount "
                        f"{indexing_count} != 1 for chunk {chunk_id}."
                    )
            except Exception as exc:
                raise self._branch_failure(
                    exc,
                    branch=VectorBranch.SPARSE,
                    step=VectorFailureStep.SQL_STATUS_WRITE,
                    chunk_id=chunk_id,
                ) from exc

        try:
            sparse_vector = await self.sparse_vector_service.vectorize_chunk(
                SparseChunkVectorizationRequest(
                    chunk_id=chunk_id,
                    content=str(getattr(record, "content")),
                    doc_id=int(getattr(record, "doc_id")),
                    bucket_id=int(getattr(record, "bucket_id")),
                    user_id=int(getattr(record, "user_id")),
                    set_id=int(getattr(record, "set_id")),
                    task_id=str(getattr(record, "doc_id")),
                    chunk_index=getattr(record, "chunk_index"),
                )
            )
        except Exception as exc:
            raise self._branch_failure(
                exc,
                branch=VectorBranch.SPARSE,
                step=VectorFailureStep.VECTOR_GENERATION,
                chunk_id=chunk_id,
            ) from exc

        try:
            sparse_point = sparse_indexed_point_from_record(
                record,
                sparse_vector,
                vector_name=self.sparse_vector_service.vector_name,
            )
            await self.qdrant_store.ensure_sparse_vector_schema(
                bucket_id=sparse_point.bucket_id,
                vector_name=sparse_point.vector_name,
            )
            await self.qdrant_store.upsert_sparse_vectors(
                bucket_id=sparse_point.bucket_id,
                points=[sparse_point],
            )
        except Exception as exc:
            raise self._branch_failure(
                exc,
                branch=VectorBranch.SPARSE,
                step=VectorFailureStep.INDEX_WRITE,
                chunk_id=chunk_id,
            ) from exc

        try:
            sparse_indexed_count = await self._mark_sparse_indexed(
                [chunk_id],
                model_name=model_name,
                nonzero_count=len(sparse_vector.indices),
            )
            if sparse_indexed_count != 1:
                raise RuntimeError(
                    "Skipped stale sparse index completion because rowcount "
                    f"{sparse_indexed_count} != 1 for chunk {chunk_id}."
                )
        except Exception as exc:
            raise self._branch_failure(
                exc,
                branch=VectorBranch.SPARSE,
                step=VectorFailureStep.SQL_STATUS_WRITE,
                chunk_id=chunk_id,
            ) from exc

        return model_name

    def _branch_failure(
        self,
        exc: Exception,
        *,
        branch: VectorBranch,
        step: VectorFailureStep,
        chunk_id: str,
    ) -> _VectorBranchFailure:
        return _VectorBranchFailure(
            str(exc),
            branch=branch,
            step=step,
            chunk_id=chunk_id,
        )

    def _retry_sleep_seconds(self) -> float:
        """
            返回当前 chunk 内联重试等待时间，并避免长时间阻塞 MQ 流程。

        Returns:
            float: 实际 sleep 秒数。
        """
        if self.retry_interval_seconds <= 0:
            return 0
        return float(min(self.retry_interval_seconds, self.max_inline_retry_sleep_seconds))

    async def _mark_indexing(
        self,
        chunk_ids: Sequence[str],
        *,
        embedding_model: str | None,
        allowed_statuses: Sequence[str] = (CHUNK_STATUS_PENDING,),
    ) -> int:
        """
            在独立事务中把目标记录切换为 `INDEXING` 状态（多值 CAS）。

        Args:
            chunk_ids: 需要更新状态的 chunk 标识列表。
            embedding_model: 当前批次实际使用的 embedding 模型名称。
            allowed_statuses: SQL 多值 CAS 的合法旧态集合；默认 ``(PENDING,)`` 服务于
                单 chunk 补偿路径，批量入口传 ``(PENDING, FAILED)`` 覆盖首次 / retry。

        Returns:
            int: 实际切换到 `INDEXING` 的记录数。
        """
        return await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_indexing(
                session,
                chunk_ids,
                embedding_model=embedding_model,
                allowed_statuses=allowed_statuses,
            )
        )

    async def _mark_indexed(
        self,
        chunk_ids: Sequence[str],
        *,
        embedding_model: str | None,
    ) -> int:
        """
            在独立事务中把目标记录切换为 `INDEXED` 状态。

        Args:
            chunk_ids: 需要更新状态的 chunk 标识列表。
            embedding_model: 当前批次实际使用的 embedding 模型名称。

        Returns:
            int: 实际切换到 `INDEXED` 的记录数。
        """
        return await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_indexed(
                session,
                chunk_ids,
                embedding_model=embedding_model,
                expected_status=CHUNK_STATUS_INDEXING,
            )
        )

    async def _safe_mark_failed(
        self,
        chunk_ids: Sequence[str],
        error_msg: str,
        *,
        expected_status: str | None = None,
    ) -> None:
        """
            尝试把目标记录安全地标记为失败状态，并吞掉二次回写异常避免链路中断。

        Args:
            chunk_ids: 需要标记失败的 chunk 标识列表。
            error_msg: 需要落库的失败原因。
            expected_status: 可选的当前状态条件，用于避免过期失败回写覆盖新状态。

        Returns:
            None.
        """
        try:
            affected_rows = await self._run_in_transaction_with_result(
                lambda session: self.repository.mark_failed(
                    session,
                    chunk_ids,
                    error_msg=error_msg,
                    expected_status=expected_status,
                )
            )
            if affected_rows != len(chunk_ids):
                logger.warning(
                    "[VectorStoragePipeline] Failed status rowcount mismatch: "
                    f"{affected_rows} != {len(chunk_ids)} for chunks {chunk_ids}."
                )
        except Exception as exc:
            logger.exception(f"[VectorStoragePipeline] Failed to mark chunks as failed: {exc}")

    async def _safe_mark_branch_failed(
        self,
        record: object,
        *,
        branch: VectorBranch,
        step: VectorFailureStep,
        error_msg: str,
    ) -> VectorCompensationEntry:
        """尽力标记失败分支，并返回不触发执行的补偿入口定位。"""

        chunk_id = str(getattr(record, "chunk_id"))
        failed_step = step
        try:
            if branch == VectorBranch.DENSE:
                await self._safe_mark_failed([chunk_id], error_msg)
            else:
                await self._safe_mark_sparse_failed([chunk_id], error_msg)
        except Exception:
            failed_step = VectorFailureStep.SQL_STATUS_WRITE
        return VectorCompensationEntry(
            document_id=int(getattr(record, "doc_id")),
            chunk_id=chunk_id,
            vector_branch=branch,
            failed_step=failed_step,
        )

    def _needs_dense(self, record: object) -> bool:
        return getattr(record, "dense_vector_status", None) in (
            CHUNK_STATUS_PENDING,
            CHUNK_STATUS_FAILED,
        )

    def _needs_sparse(self, record: object) -> bool:
        # Sparse indexing is an independent file-level stage in ParseTaskPipeline.
        # Vectorizing only handles dense vectors; sparse retries are selected by
        # SparseIndexingPipeline from sparse_vector_status.
        return False

    def _sparse_enabled(self) -> bool:
        """判断当前向量写入流程是否启用 sparse 子能力。"""

        return bool(getattr(settings, "SPARSE_VECTOR_ENABLED", False))

    def _sparse_model_name(self) -> str | None:
        """返回 sparse 服务使用的模型名；未配置服务时返回 None。"""

        return self.sparse_vector_service.model_name if self.sparse_vector_service else None

    async def _mark_sparse_indexing(
        self,
        chunk_ids: Sequence[str],
        *,
        model_name: str | None,
        allowed_statuses: Sequence[str] = (SPARSE_VECTOR_STATUS_PENDING,),
    ) -> int:
        """把当前 chunk 的 sparse 子状态切换为 INDEXING（多值 CAS）。

        ``allowed_statuses`` 默认 ``(PENDING,)`` 服务于单 chunk 补偿路径；批量入口
        传 ``(PENDING, FAILED)`` 覆盖首次 / retry 两种合法旧态。
        """

        if self.sparse_vector_service is None:
            raise RuntimeError(
                "SPARSE_VECTOR_ENABLED=true but sparse vector service is not configured."
            )
        return await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_sparse_indexing(
                session,
                chunk_ids,
                model_name=model_name,
                allowed_statuses=allowed_statuses,
            )
        )

    async def _mark_sparse_indexed(
        self,
        chunk_ids: Sequence[str],
        *,
        model_name: str | None,
        nonzero_count: int,
    ) -> int:
        """把当前 chunk 的 sparse 子状态切换为 SUCCESS 并记录非零 token 数。"""

        return await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_sparse_indexed(
                session,
                chunk_ids,
                model_name=model_name,
                nonzero_count=nonzero_count,
                expected_status=SPARSE_VECTOR_STATUS_INDEXING,
            )
        )

    async def _safe_mark_sparse_failed(self, chunk_ids: Sequence[str], error_msg: str) -> None:
        """尽力把 sparse 子状态标记为 FAILED，避免二次异常中断主失败流程。"""

        try:
            affected_rows = await self._run_in_transaction_with_result(
                lambda session: self.repository.mark_sparse_failed(
                    session,
                    chunk_ids,
                    error_msg=error_msg,
                    expected_status=None,
                )
            )
            if affected_rows != len(chunk_ids):
                logger.warning(
                    "[VectorStoragePipeline] Sparse failed status rowcount mismatch: "
                    f"{affected_rows} != {len(chunk_ids)} for chunks {chunk_ids}."
                )
        except Exception as exc:
            logger.exception(
                f"[VectorStoragePipeline] Failed to mark sparse chunks as failed: {exc}"
            )

    async def _ensure_and_upsert(self, points: Sequence[IndexedPoint]) -> None:
        """
            先按桶分组 point，再逐桶确保 collection 存在并执行 upsert。

        Args:
            points: 待写入 Qdrant 的标准化 point 序列。

        Returns:
            None.
        """
        grouped_points: dict[int, list[IndexedPoint]] = defaultdict(list)
        for point in points:
            grouped_points[point.bucket_id].append(point)

        for bucket_id, bucket_points in grouped_points.items():
            await self.qdrant_store.ensure_collection(
                bucket_id=bucket_id,
                vector_size=len(bucket_points[0].vector),
            )
            await self.qdrant_store.upsert_points(bucket_id=bucket_id, points=bucket_points)

    def _resolve_embedding_model(
        self,
        embedded_chunks: Sequence[object],
        *,
        pipeline: ChunkEmbeddingPipeline | None = None,
    ) -> str | None:
        """
            从本次 embedding 输出中推断实际使用的模型名称，并在必要时回退到管线统计值。

        Args:
            embedded_chunks: 本次向量化产出的结果列表。
            pipeline: 本次实际使用的 embedding 管线；LINK-91 后 dense 写入按用户解析
                per-user 管线，需取该管线的 ``last_stats`` 而非进程级 ``self.embedding_pipeline``。
                缺省回退到注入的进程级管线（兼容补偿/管理路径）。

        Returns:
            str | None: 实际使用的 embedding 模型名称。
        """
        for embedded_chunk in embedded_chunks:
            if embedded_chunk.embedding_model:
                return embedded_chunk.embedding_model
        stats = getattr(pipeline or self.embedding_pipeline, "last_stats", None)
        return getattr(stats, "embedding_model", None)
