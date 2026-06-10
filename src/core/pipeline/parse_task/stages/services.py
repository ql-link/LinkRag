"""StageServices：解析阶段共享的底层操作集合。

把 cleaning/chunking/vectorizing/pretokenize/es/sparse 各阶段需要的纯 IO 与
计算操作（解析、分片、向量化、预分词、ES 写入、稀疏向量化、chunk 反查等）集中
于此。:class:`~.base.Stage` 子类只做编排，不直接持有这些重依赖的装配细节；
重依赖（向量库、ES、预分词、稀疏模型）统一在此懒加载，支持测试注入。

本类**不写 ``document_parse_pipeline`` 阶段状态、不发 MQ 通知**——状态机与
通知由各 Stage 通过 repository / notifier 处理，保证副作用边界清晰。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger

if TYPE_CHECKING:
    from src.core.dataset_config import ChunkingConfig, DatasetParseConfigBundle

from src.config import settings
from src.core.chunk_fact_storage.constants import (
    CHUNK_LIFECYCLE_ACTIVE,
    CHUNK_STATUS_INDEXED,
    SPARSE_VECTOR_STATUS_INDEXED,
)
from src.core.chunk_fact_storage.repository import ChunkRepository
from src.core.es_index_storage import EsIndexingPipeline, EsIndexingResult
from src.core.markdown_parser import ParseResult
from src.core.mq.messages.parse_task import ParseTaskPayload
from src.core.preprocessor.models import FilePostIndexPlan
from src.core.qdrant_vector_storage import BucketRouter
from src.core.qdrant_vector_storage.constants import DEFAULT_BUCKET_COUNT, DEFAULT_COLLECTION_PREFIX
from src.core.splitter import create_chunking_engine
from src.core.splitter.factory import (
    DenseEmbeddingConfigMissingError,
    DenseEmbeddingDimensionError,
)
from src.core.splitter.models import Chunk
from src.core.vector_storage import compose_vector_storage_facade
from src.core.vector_storage.draft_factory import ChunkDraftFactory
from src.core.vector_storage.models import ChunkIndexingResult
from src.models.chunk_record import ChunkRecordDB
from src.services.parse_task_service import ParseTaskService
from src.services.storage.base import BaseObjectStorage
from sqlalchemy.ext.asyncio import AsyncSession

from .._utils import coerce_optional_int
from ..source import ParseSourceIO


class PreprocessorProtocol(Protocol):
    """解析流水线消费的最小预分词接口。"""

    async def build_file_post_index_plan(
        self,
        *,
        doc_id: int,
        task_id: str,
    ) -> FilePostIndexPlan: ...


class StageServices:
    """阶段共享底层操作；重依赖懒加载，支持测试注入。"""

    def __init__(
        self,
        *,
        storage: BaseObjectStorage,
        source_io: ParseSourceIO,
        chunk_repository: ChunkRepository,
        vector_storage: Any | None = None,
        es_indexing_pipeline: Any | None = None,
        preprocessor: PreprocessorProtocol | None = None,
        chunk_draft_factory: ChunkDraftFactory | None = None,
        sparse_indexing_pipeline: Any | None = None,
    ) -> None:
        self._storage = storage
        self.source_io = source_io
        self._chunk_repository = chunk_repository
        self._vector_storage = vector_storage
        self._es_indexing_pipeline = es_indexing_pipeline
        self._preprocessor = preprocessor
        self._chunk_draft_factory = chunk_draft_factory
        self._sparse_indexing_pipeline = sparse_indexing_pipeline

    # ------------------------------------------------------------------
    # cleaning
    # ------------------------------------------------------------------

    async def parse_file(
        self,
        source_path: Path | None,
        payload: ParseTaskPayload,
        dataset_cfg: "DatasetParseConfigBundle | None" = None,
    ) -> dict:
        """调用解析服务生成 Markdown 与结构化解析结果。

        ``source_path`` 为 ``None`` 仅出现在 MinerU URL 旁路场景；其余路径下必须是
        已经流式下载完成的本地临时文件路径。

        ``dataset_cfg`` 为数据集级配置（由 CleaningStage 从 DB 读取注入）：PDF 后端按
        ``payload 显式 > 数据集配置 > settings.PDF_PARSER_BACKEND`` 三层优先级选取；
        Markdown 增强配置（含 table/vision 模型名与开关）透传给增强编排。``None`` 时全部回退
        系统默认，行为与拆分前一致。
        """
        enhancement_config = dataset_cfg.enhancement if dataset_cfg is not None else None

        parser_kwargs: dict[str, Any] = {}
        if payload.file_type.lower() == "pdf":
            dataset_backend = (
                dataset_cfg.pdf.pdf_parser_backend if dataset_cfg is not None else None
            )
            # 三层优先级：payload 显式指定 > 数据集级配置 > 系统默认（默认 mineru，与原硬编码一致）。
            pdf_backend = (
                payload.pdf_parser_backend or dataset_backend or settings.PDF_PARSER_BACKEND
            )
            parser_kwargs = {
                "backend": pdf_backend,
                "docling_force_ocr": bool(payload.docling_force_ocr),
                "image_bucket": payload.image_bucket or payload.md_bucket,
                "image_prefix": payload.image_prefix or payload.md_object_key,
                "storage": self._storage,
            }
            if pdf_backend.lower() == "mineru":
                parser_kwargs["source_file_url"] = self.source_io.build_source_file_url(payload)

        return await ParseTaskService.aprocess(
            source_path,
            payload.file_type,
            source_file=payload.source_filename or payload.md_object_key,
            user_id=coerce_optional_int(payload.user_id),
            enhancement_config=enhancement_config,
            **parser_kwargs,
        )

    async def load_markdown(self, payload: ParseTaskPayload) -> str:
        """从对象存储读回已上传的 Markdown 文本（重试从 CHUNKING 恢复时使用）。

        ``cleaning`` 已成功的重试会跳过解析+上传，但「从 CHUNKING 重新分片」需要旧
        markdown 作为分片输入。沿用 ``download_to_path`` 流式下载到临时文件再读取，
        不在内存拼接完整对象，与源文件下载保持同一 OOM 安全约束。
        """
        import asyncio

        from .. import temp_workspace

        path = temp_workspace.create_temp_file(payload.task_id, Path(settings.PARSE_TEMP_DIR))
        try:
            # markdown 真实位置经 payload 解析：md/markdown 取上传位置（source_*），
            # 其余格式取 cleaning 写出的 md_*；不可硬编码 md_bucket，否则 md 重试读不到。
            await asyncio.to_thread(
                self._storage.download_to_path,
                payload.markdown_bucket,
                payload.markdown_object_key,
                path,
            )
            return await asyncio.to_thread(path.read_text, "utf-8")
        finally:
            temp_workspace.safe_unlink(path)

    # ------------------------------------------------------------------
    # chunking
    # ------------------------------------------------------------------

    async def run_chunking(
        self,
        markdown: str,
        parse_result: ParseResult | None,
        payload: ParseTaskPayload,
        db: AsyncSession,
        chunking_config: "ChunkingConfig | None" = None,
    ) -> list[ChunkRecordDB]:
        """分片并在单事务内写入 chunk 真值记录；返回当前文档完整 chunk truth set（ORM 行）。

        ``chunking_config`` 为数据集级分块配置（由 ChunkingStage 从 DB 读取注入）；``None`` 时
        分片引擎取全默认配置，行为与拆分前一致。

        ``_persist_chunk_facts`` commit 后追加一次按 ``doc_id`` 的反查，让首次链路的
        ``chunks`` 形态与 retry 链路（``load_all_chunks_from_db``）完全一致——都是
        ``list[ChunkRecordDB]``。下游 dense / sparse 入口因此能用同一套字段契约消费，
        不区分首次 / retry 场景。
        """
        import asyncio

        chunks = await asyncio.to_thread(
            self._chunk_markdown,
            markdown,
            payload.md_object_key,
            parse_result,
            chunking_config,
        )
        await self._persist_chunk_facts(chunks, payload, db)

        # commit 后立即反查 ORM 行作为返回值（与 retry 路径形态一致）。
        records = await self._reload_chunks_from_db(payload, db)
        logger.info(
            f"[StageServices] chunking completed: task_id={payload.task_id}, "
            f"chunk_count={len(records)}"
        )
        return records

    async def _reload_chunks_from_db(
        self,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> list[ChunkRecordDB]:
        """按 ``doc_id`` 反查当前文档完整 chunk truth set（仅 ACTIVE，按 ``chunk_index`` 升序）。

        chunks 反查的唯一 SQL 实现，三个调用点共享：

        * ``run_chunking``：commit 后立即反查，作为返回值。
        * ``load_all_chunks_from_db``：retry 路径加空集兜底后返回。
        * ``run_sparse_vectorizing``：dense 完成后重新 load 一次，确保 sparse 阶段
          读到刷新后的 ``dense_vector_status``。
        """
        from sqlalchemy import select

        doc_id = int(payload.original_file_id)
        stmt = (
            select(ChunkRecordDB)
            .where(ChunkRecordDB.doc_id == doc_id)
            .where(ChunkRecordDB.lifecycle_status == CHUNK_LIFECYCLE_ACTIVE)
            .order_by(ChunkRecordDB.chunk_index.asc())
            # populate_existing：dense 阶段在独立 session 写 dense_vector_status=SUCCESS，
            # 而本 session 的 expire_on_commit=False 会让身份映射里 chunking 阶段加载的同主键
            # ORM 对象保持旧值（PENDING）。不强制刷新则 sparse 入口按 dense==SUCCESS 过滤恒为空，
            # 稀疏索引永不写入。populate_existing 用查询结果覆盖已加载实例的属性，读到最新真值。
            .execution_options(populate_existing=True)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def _persist_chunk_facts(
        self,
        chunks: list[Chunk],
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> None:
        owner = self.resolve_chunk_owner(payload)
        if owner is None:
            raise RuntimeError("chunk owner is missing")
        user_id, set_id, doc_id = owner
        drafts = self._get_chunk_draft_factory().build_drafts(
            user_id=user_id,
            set_id=set_id,
            doc_id=doc_id,
            chunks=chunks,
        )
        try:
            if payload.is_retry:
                # 重试重建 chunk truth set：先清本文档残留再全量写入，使「清旧+写新」同事务原子化，
                # 避免旧 chunking 半成品或上一轮残片与本轮派生的同名 chunk_id 撞唯一键。
                await self._chunk_repository.delete_by_doc_id(db, doc_id)
            await self._chunk_repository.bulk_insert_pending(db, drafts)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    def _chunk_markdown(
        markdown: str,
        source_file: str | None,
        parse_result: ParseResult | None = None,
        chunking_config: "ChunkingConfig | None" = None,
    ) -> list[Chunk]:
        processor = create_chunking_engine(config=chunking_config)
        if parse_result is None:
            return processor.process(markdown, source_file=source_file)
        parse_result_for_chunking = replace(parse_result, source_file=source_file)
        return processor.process_parse_result(parse_result_for_chunking)

    async def load_all_chunks_from_db(
        self,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> list[ChunkRecordDB]:
        """重试跳过 chunking 时从 DB 反查当前文档完整 chunk truth set（ORM 行）。

        反查谓词：``doc_id`` + ``lifecycle_status=ACTIVE``，按 ``chunk_index`` 排序。
        不再 ``chunk_from_record`` 包成 splitter ``Chunk``——dense / sparse 入口现在直接
        消费 ORM 行（按字段契约访问）。返回空列表表示状态不一致（chunking 标 SUCCESS
        但无有效 chunk），由 ChunkingStage 落 FAILED + 通知。
        """
        return await self._reload_chunks_from_db(payload, db)

    def resolve_chunk_owner(self, payload: ParseTaskPayload) -> tuple[int, int, int] | None:
        """解析 chunk 向量索引所需的归属标识（user/set/doc）。"""
        user_id = coerce_optional_int(payload.user_id)
        set_id = coerce_optional_int(payload.dataset_id)
        doc_id = coerce_optional_int(payload.original_file_id)
        if user_id is None or set_id is None or doc_id is None:
            return None
        return user_id, set_id, doc_id

    # ------------------------------------------------------------------
    # vectorizing (dense)
    # ------------------------------------------------------------------

    async def store_chunk_vectors(
        self,
        chunks: list[ChunkRecordDB],
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> ChunkIndexingResult:
        """将 chunk 写入向量存储（dense/Qdrant）。

        ``chunks`` 是 ``list[ChunkRecordDB]``（首次链路 ``run_chunking`` 反查、retry 链路
        ``load_all_chunks_from_db`` 反查，形态一致）。调用 dense 入口前**现场过滤**
        ``dense_vector_status != SUCCESS`` 的 chunk，dense 模块只处理传入子集、不再自查 SQL。
        入口从 ``index_document_chunks(include_failed=...)`` 切到 ``index_chunks(chunks=...)``：
        dense 不感知首次 / retry，多值 CAS 在 SQL 层兜底两种共用入口。
        """
        if not chunks:
            return ChunkIndexingResult(total_chunks=0, indexed_chunks=0)

        owner = self.resolve_chunk_owner(payload)
        if owner is None:
            logger.warning(
                "[StageServices] skip vector indexing because owner is missing: task_id={}",
                payload.task_id,
            )
            return ChunkIndexingResult(
                total_chunks=len(chunks),
                indexed_chunks=0,
                failed_chunk_ids=self.fallback_chunk_ids(chunks),
            )

        user_id, set_id, doc_id = owner

        # 现场过滤：dense_vector_status != SUCCESS（覆盖首次 PENDING 与 retry 的 PENDING / FAILED）。
        dense_chunks = [c for c in chunks if c.dense_vector_status != CHUNK_STATUS_INDEXED]
        if not dense_chunks:
            # 全部已 SUCCESS：等价于无事可做，幂等成功。
            return ChunkIndexingResult(
                total_chunks=len(chunks),
                indexed_chunks=len(chunks),
            )

        try:
            result = await self._get_vector_storage().index_chunks(
                user_id=user_id,
                set_id=set_id,
                doc_id=doc_id,
                chunks=dense_chunks,
            )
        except (DenseEmbeddingConfigMissingError, DenseEmbeddingDimensionError):
            # 必配缺失 / 维度不支持：交给 VectorizingStage 归类为明确错误码（LLM_CONFIG_MISSING /
            # EMBEDDING_DIMENSION_UNSUPPORTED）并通知 Java，不在此吞成 generic 失败结果。
            raise
        except Exception as exc:
            logger.error(
                "[StageServices] vector indexing failed: task_id={} error={}",
                payload.task_id,
                exc,
            )
            return ChunkIndexingResult(
                total_chunks=len(chunks),
                indexed_chunks=0,
                failed_chunk_ids=self.fallback_chunk_ids(chunks),
            )

        if result.failed_chunk_ids:
            logger.warning(
                "[StageServices] vector indexing has failed chunks: "
                "task_id={} total={} indexed={} failed={}",
                payload.task_id,
                result.total_chunks,
                result.indexed_chunks,
                result.failed_chunk_ids,
            )
        else:
            logger.info(
                "[StageServices] vector indexing completed: task_id={} indexed={} model={}",
                payload.task_id,
                result.indexed_chunks,
                result.embedding_model,
            )
        return result

    @staticmethod
    def fallback_chunk_ids(chunks: list[ChunkRecordDB]) -> list[str]:
        """从 ORM 行序列提取真实 ``chunk_id`` 作为兜底失败标识，便于运维定位。"""
        return [c.chunk_id for c in chunks]

    @staticmethod
    def is_vector_indexing_success(vector_result: ChunkIndexingResult) -> bool:
        return vector_result.is_success

    @staticmethod
    def build_vector_failure_reason(vector_result: ChunkIndexingResult) -> str:
        failed_count = len(vector_result.failed_chunk_ids)
        reason = (
            "VECTORIZING_FAILED: 向量化失败；"
            f"total={vector_result.total_chunks}, indexed={vector_result.indexed_chunks}, "
            f"failed={failed_count}"
        )
        if vector_result.compensation_entry is not None:
            entry = vector_result.compensation_entry
            reason = (
                f"{reason}, chunk_id={entry.chunk_id}, "
                f"branch={entry.vector_branch.value}, step={entry.failed_step.value}"
            )
        return reason

    # ------------------------------------------------------------------
    # pretokenize
    # ------------------------------------------------------------------

    async def build_pretokenize_plan(
        self,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> tuple[FilePostIndexPlan | None, str | None]:
        """构建内存态 ``FilePostIndexPlan``（不持久化、不写阶段状态）。

        成功返回 ``(plan, None)``；失败返回 ``(None, reason)``。空 plan 但仍有
        待入库 chunk 视为失败（文件级 all-or-nothing）。
        """
        doc_id = int(payload.original_file_id)
        try:
            plan = await self._get_preprocessor().build_file_post_index_plan(
                doc_id=doc_id,
                task_id=payload.task_id,
            )
        except Exception as exc:
            reason = str(exc)
            if not reason.startswith("pretokenize:"):
                reason = f"pretokenize: {reason}"
            return None, reason

        if len(plan.chunks_with_tokens) == 0:
            pending = await self._chunk_repository.count_es_not_success_by_doc_id(db, doc_id)
            if pending > 0:
                return None, f"pretokenize: empty plan but {pending} chunks pending"

        return plan, None

    # ------------------------------------------------------------------
    # es_indexing
    # ------------------------------------------------------------------

    async def run_es_indexing(
        self,
        plan: FilePostIndexPlan,
        db: AsyncSession,
    ) -> EsIndexingResult:
        """ES 入库：文档级全量重建（Issue #57）——前置删除 → 全量写入 → 失败清理。"""
        total = len(plan.chunks_with_tokens)
        if total == 0:
            return EsIndexingResult(total_items=0, indexed_items=0)

        es_pipeline = self._get_es_indexing_pipeline()
        meta = plan.file_meta

        try:
            await es_pipeline.delete_document_index(
                user_id=meta.user_id,
                dataset_id=meta.dataset_id,
                doc_id=meta.doc_id,
            )
        except Exception as exc:
            logger.error(
                "[StageServices] ES 前置删除失败，判 ES 阶段失败不写入: doc_id={} error={}",
                meta.doc_id,
                exc,
            )
            return EsIndexingResult(
                total_items=total,
                indexed_items=0,
                failure_reason=f"es_delete: {exc}",
            )

        result = await es_pipeline.write_es_index(plan, db=db)

        if not result.is_success:
            try:
                await es_pipeline.delete_document_index(
                    user_id=meta.user_id,
                    dataset_id=meta.dataset_id,
                    doc_id=meta.doc_id,
                )
            except Exception as exc:
                logger.warning(
                    "[StageServices] ES 写入失败后清理半成品失败(best-effort): doc_id={} error={}",
                    meta.doc_id,
                    exc,
                )

        return result

    @staticmethod
    def build_es_failure_reason(es_result: EsIndexingResult) -> str:
        failed_count = len(es_result.failed_item_ids)
        return (
            "ES_INDEXING_FAILED: ES入库失败；"
            f"total={es_result.total_items}, indexed={es_result.indexed_items}, "
            f"failed={failed_count}"
        )

    # ------------------------------------------------------------------
    # sparse_vectorizing
    # ------------------------------------------------------------------

    async def run_sparse_vectorizing(
        self,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> None:
        """调用 SparseIndexingPipeline.run；失败抛出（由 SparseVectorizingStage 归类）。

        dense 阶段已推进 ``dense_vector_status``，这里**重新 load** 一次 chunks 以读到
        刷新后的视图，再**现场过滤** ``dense=SUCCESS AND sparse != SUCCESS`` 后透传给
        sparse 入口。sparse 模块不再自查 SQL，``bucket_id`` 由 chunks 自带字段决定
        （不再误传 ``payload.dataset_id``）。
        """
        from src.core.sparse_vector.indexing import SparseIndexingPipeline

        sparse_pipeline = self._sparse_indexing_pipeline or SparseIndexingPipeline()

        fresh_chunks = await self._reload_chunks_from_db(payload, db)
        sparse_chunks = [
            c
            for c in fresh_chunks
            if c.dense_vector_status == CHUNK_STATUS_INDEXED
            and c.sparse_vector_status != SPARSE_VECTOR_STATUS_INDEXED
        ]
        await sparse_pipeline.run(
            chunks=sparse_chunks,
            task_id=payload.task_id,
            db=db,
        )

    # ------------------------------------------------------------------
    # 懒加载装配
    # ------------------------------------------------------------------

    def _get_chunk_draft_factory(self) -> ChunkDraftFactory:
        if self._chunk_draft_factory is None:
            bucket_router = BucketRouter(
                bucket_count=getattr(settings, "CHUNK_INDEX_BUCKET_COUNT", DEFAULT_BUCKET_COUNT),
                prefix=getattr(
                    settings, "CHUNK_INDEX_COLLECTION_PREFIX", DEFAULT_COLLECTION_PREFIX
                ),
            )
            self._chunk_draft_factory = ChunkDraftFactory(bucket_router=bucket_router)
        return self._chunk_draft_factory

    def _get_vector_storage(self):
        if self._vector_storage is None:
            self._vector_storage = compose_vector_storage_facade()
        return self._vector_storage

    def _get_es_indexing_pipeline(self):
        if self._es_indexing_pipeline is None:
            self._es_indexing_pipeline = EsIndexingPipeline(
                chunk_repository=self._chunk_repository,
            )
        return self._es_indexing_pipeline

    def _get_preprocessor(self) -> PreprocessorProtocol:
        if self._preprocessor is not None:
            return self._preprocessor
        try:
            from src.core.preprocessor.service import Preprocessor
        except Exception as exc:
            raise RuntimeError("preprocessor service is not available") from exc
        self._preprocessor = Preprocessor()
        return self._preprocessor
