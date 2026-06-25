"""Parse-task workflow demo nodes.

This module wraps existing ``StageServices`` operations as workflow nodes. It is
not wired into the production parse-task MQ consumer; the current stage-based
pipeline remains available in parallel.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.dataset_config import DatasetConfigService
from src.core.pipeline.parse_task import temp_workspace
from src.core.pipeline.parse_task._utils import coerce_optional_int
from src.core.pipeline.parse_task.stages.services import StageServices
from src.core.workflow.context import WorkflowContext
from src.core.workflow.node import WorkflowNode
from src.core.mq.messages.parse_task import ParseTaskPayload

from . import product_keys as products


@dataclass
class ParseWorkflowRuntime:
    """Runtime dependencies and transient artifacts for one demo workflow run.

    ``session_factory`` (not a shared session) is the deliberate choice: in the
    parallel DAG several nodes run concurrently, and a single ``AsyncSession`` is
    NOT safe for concurrent use — concurrent reads on one session return empty /
    inconsistent results. Each node therefore opens its own short-lived session via
    :meth:`session`, so concurrent nodes get independent connections.
    """

    payload: ParseTaskPayload
    session_factory: Callable[[], AsyncSession]
    services: StageServices
    source_path: Path | None = None
    parse_result: dict[str, Any] | None = None
    chunks: list[Any] | None = None
    vector_result: Any | None = None
    plan: Any | None = None

    def session(self) -> AsyncSession:
        """Open a fresh DB session/connection for one node's work."""
        return self.session_factory()


class CleaningNode(WorkflowNode):
    def __init__(self, *, extra_requires: tuple[str, ...] = ()) -> None:
        super().__init__(
            key="cleaning",
            requires=(products.SOURCE, *extra_requires),
            provides=(products.MARKDOWN,),
        )

    async def run(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        payload = runtime.payload
        source_path = runtime.source_path
        created_source_path = False

        try:
            if not runtime.services.source_io.should_skip_source_download(payload):
                if source_path is None:
                    source_path = temp_workspace.create_temp_file(
                        payload.task_id,
                        Path(settings.PARSE_TEMP_DIR),
                        suffix=payload.file_type,
                    )
                    created_source_path = True
                    await asyncio.to_thread(
                        runtime.services.source_io.download_to_path,
                        payload,
                        source_path,
                    )

            if payload.is_markdown_passthrough:
                if source_path is None:
                    raise ValueError("markdown passthrough requires a source file path")
                markdown = await asyncio.to_thread(
                    Path(source_path).read_text,
                    "utf-8",
                    "ignore",
                )
                parse_result = {
                    "markdown": markdown,
                    "parse_result": None,
                    "metadata": {
                        "format": "markdown",
                        "passthrough": True,
                        "pages_or_length": len(markdown),
                    },
                    "time_cost_ms": 0,
                }
            else:
                async with runtime.session() as db:
                    dataset_cfg = await _load_dataset_config(runtime, db)
                parse_started_at = time.monotonic()
                parse_result = await runtime.services.parse_file(
                    source_path,
                    payload,
                    dataset_cfg,
                )
                parse_result.setdefault(
                    "time_cost_ms",
                    int((time.monotonic() - parse_started_at) * 1000),
                )
                await asyncio.to_thread(
                    runtime.services.source_io.upload_markdown,
                    payload,
                    parse_result["markdown"],
                )

            runtime.parse_result = parse_result
            ctx.set(products.MARKDOWN, parse_result["markdown"])
            return _markdown_ref(payload, parse_result)
        finally:
            if created_source_path:
                temp_workspace.safe_unlink(source_path)

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        runtime = _runtime(ctx)
        markdown = await runtime.services.load_markdown(runtime.payload)
        runtime.parse_result = {
            "markdown": markdown,
            "parse_result": None,
            "metadata": {"restored_from": output_ref},
            "time_cost_ms": 0,
        }
        ctx.set(products.MARKDOWN, markdown)


class ChunkingNode(WorkflowNode):
    def __init__(self, *, extra_requires: tuple[str, ...] = ()) -> None:
        super().__init__(
            key="chunking",
            requires=(products.MARKDOWN, *extra_requires),
            provides=(products.CHUNKS,),
        )

    async def run(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        parse_result = runtime.parse_result or {
            "markdown": ctx.require(products.MARKDOWN),
            "parse_result": None,
        }
        async with runtime.session() as db:
            bundle = await _load_dataset_config(runtime, db)
            chunking_config = bundle.chunking if bundle is not None else None
            chunks = await runtime.services.run_chunking(
                parse_result["markdown"],
                parse_result.get("parse_result"),
                runtime.payload,
                db,
                chunking_config,
            )
        runtime.chunks = chunks
        ctx.set(products.CHUNKS, chunks)
        return _chunks_ref(runtime.payload, chunks)

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        runtime = _runtime(ctx)
        async with runtime.session() as db:
            chunks = await runtime.services.load_all_chunks_from_db(runtime.payload, db)
        if not chunks:
            raise RuntimeError("workflow demo restore failed: chunk set is empty")
        runtime.chunks = chunks
        ctx.set(products.CHUNKS, chunks)


class EnsurePointsNode(WorkflowNode):
    """在 dense/sparse 扇出前，按 payload 预建 Qdrant point（解耦的关键前置）。

    单写者建点，避免 dense 与 sparse 并发各自建点相互覆盖；建好后两者只 update_vectors
    各自的 named 向量，可真正并行。
    """

    def __init__(self, *, extra_requires: tuple[str, ...] = ()) -> None:
        super().__init__(
            key="ensure_points",
            requires=(products.CHUNKS, *extra_requires),
            provides=(products.POINTS_READY,),
        )

    async def run(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        chunks = list(ctx.require(products.CHUNKS) or [])
        async with runtime.session() as db:
            await runtime.services.ensure_chunk_points(chunks, runtime.payload, db)
        output_ref = {"doc_id": runtime.payload.original_file_id, "points": len(chunks)}
        ctx.set(products.POINTS_READY, output_ref)
        return output_ref

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        # 建点是幂等的（create-if-missing）：续跑时重建一次即可恢复产物。
        runtime = _runtime(ctx)
        chunks = list(runtime.chunks or ctx.get(products.CHUNKS) or [])
        async with runtime.session() as db:
            await runtime.services.ensure_chunk_points(chunks, runtime.payload, db)
        ctx.set(products.POINTS_READY, output_ref)


class DenseVectorizingNode(WorkflowNode):
    def __init__(self, *, extra_requires: tuple[str, ...] = ()) -> None:
        # dense 同时依赖两件事，必须都声明：
        #   - POINTS_READY：point 已由 ensure_points 建好，dense 只 update_vectors 写
        #     dense named 向量（不再负责建 point，与 sparse 解耦、可并行）。
        #   - CHUNKS：run() 从 ctx 取 chunk 文本做向量化。续跑时引擎只按声明的 requires
        #     回放上游产物——不声明 CHUNKS，则 chunking 不会被 restore，ctx 缺 parse.chunks。
        # ensure_points 本身依赖 chunking，故加这条边不损失并行度（dense 仍 ∥ sparse ∥ es）。
        super().__init__(
            key="dense_vectorizing",
            requires=(products.CHUNKS, products.POINTS_READY, *extra_requires),
            provides=(products.DENSE_VECTORS,),
        )

    async def run(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        chunks = list(ctx.require(products.CHUNKS) or [])
        async with runtime.session() as db:
            vector_result = await runtime.services.store_chunk_vectors(
                chunks,
                runtime.payload,
                db,
            )
        runtime.vector_result = vector_result
        if not runtime.services.is_vector_indexing_success(vector_result):
            raise RuntimeError(runtime.services.build_vector_failure_reason(vector_result))
        output_ref = {
            "doc_id": runtime.payload.original_file_id,
            "total_chunks": vector_result.total_chunks,
            "indexed_chunks": vector_result.indexed_chunks,
            "embedding_model": vector_result.embedding_model,
        }
        ctx.set(products.DENSE_VECTORS, output_ref)
        return output_ref

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        ctx.set(products.DENSE_VECTORS, output_ref)


class PretokenizeNode(WorkflowNode):
    def __init__(self, *, extra_requires: tuple[str, ...] = ()) -> None:
        # ES 与 dense 解耦后，pretokenize 只需 chunk（按 lifecycle=ACTIVE 取全集），
        # 不再依赖 dense，可与 dense/sparse 并行。
        super().__init__(
            key="pretokenize",
            requires=(products.CHUNKS, *extra_requires),
            provides=(products.TOKENS,),
        )

    async def run(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        async with runtime.session() as db:
            plan, reason = await runtime.services.build_pretokenize_plan(runtime.payload, db)
        if reason is not None:
            raise RuntimeError(reason)
        runtime.plan = plan
        ctx.set(products.TOKENS, plan)
        return _plan_ref(runtime.payload, plan)

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        runtime = _runtime(ctx)
        async with runtime.session() as db:
            plan, reason = await runtime.services.build_pretokenize_plan(runtime.payload, db)
        if reason is not None:
            raise RuntimeError(reason)
        runtime.plan = plan
        ctx.set(products.TOKENS, plan)


class EsIndexingNode(WorkflowNode):
    def __init__(self, *, extra_requires: tuple[str, ...] = ()) -> None:
        super().__init__(
            key="es_indexing",
            requires=(products.TOKENS, *extra_requires),
            provides=(products.ES_INDEX,),
        )

    async def run(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        plan = runtime.plan or ctx.require(products.TOKENS)
        async with runtime.session() as db:
            es_result = await runtime.services.run_es_indexing(plan, db)
        if not es_result.is_success:
            reason = es_result.failure_reason or runtime.services.build_es_failure_reason(es_result)
            raise RuntimeError(reason)
        output_ref = {
            "doc_id": runtime.payload.original_file_id,
            "total_items": es_result.total_items,
            "indexed_items": es_result.indexed_items,
        }
        ctx.set(products.ES_INDEX, output_ref)
        return output_ref

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        ctx.set(products.ES_INDEX, output_ref)


class SparseVectorizingNode(WorkflowNode):
    def __init__(self, *, extra_requires: tuple[str, ...] = ()) -> None:
        # 解耦后 sparse 不再依赖 dense：point 由 ensure_points 建好，sparse 只
        # update_vectors 写 sparse named 向量，可与 dense 并行。依赖 POINTS_READY。
        super().__init__(
            key="sparse_vectorizing",
            requires=(products.POINTS_READY, *extra_requires),
            provides=(products.SPARSE_VECTORS,),
        )

    async def run(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        async with runtime.session() as db:
            await runtime.services.run_sparse_vectorizing(runtime.payload, db)
        output_ref = {"doc_id": runtime.payload.original_file_id}
        ctx.set(products.SPARSE_VECTORS, output_ref)
        return output_ref

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        ctx.set(products.SPARSE_VECTORS, output_ref)


def _runtime(ctx: WorkflowContext) -> ParseWorkflowRuntime:
    runtime = ctx.require(products.SOURCE)
    if not isinstance(runtime, ParseWorkflowRuntime):
        raise TypeError("parse workflow demo requires ParseWorkflowRuntime as source product")
    return runtime


async def _load_dataset_config(runtime: ParseWorkflowRuntime, db: AsyncSession):
    user_id = coerce_optional_int(runtime.payload.user_id)
    dataset_id = coerce_optional_int(runtime.payload.dataset_id)
    if user_id is None or dataset_id is None:
        return None
    return await DatasetConfigService().get_config(user_id, dataset_id, db)


def _markdown_ref(payload: ParseTaskPayload, parse_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "bucket": payload.markdown_bucket,
        "object_key": payload.markdown_object_key,
        "chars": len(parse_result.get("markdown") or ""),
        "time_cost_ms": parse_result.get("time_cost_ms"),
    }


def _chunks_ref(payload: ParseTaskPayload, chunks: list[Any]) -> dict[str, Any]:
    return {
        "doc_id": payload.original_file_id,
        "chunk_count": len(chunks),
        "chunk_ids": [getattr(chunk, "chunk_id", None) for chunk in chunks],
    }


def _plan_ref(payload: ParseTaskPayload, plan: Any) -> dict[str, Any]:
    return {
        "doc_id": payload.original_file_id,
        "chunk_count": len(getattr(plan, "chunks_with_tokens", []) or []),
    }
