"""Parse-task workflow demo nodes.

This module wraps existing ``StageServices`` operations as workflow nodes. It is
not wired into the production parse-task MQ consumer; the current stage-based
pipeline remains available in parallel.
"""

from __future__ import annotations

import asyncio
import time
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
    """Runtime dependencies and transient artifacts for one demo workflow run."""

    payload: ParseTaskPayload
    db: AsyncSession
    services: StageServices
    source_path: Path | None = None
    parse_result: dict[str, Any] | None = None
    chunks: list[Any] | None = None
    vector_result: Any | None = None
    plan: Any | None = None


class CleaningNode(WorkflowNode):
    def __init__(self) -> None:
        super().__init__(
            key="cleaning",
            requires=(products.SOURCE,),
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
                dataset_cfg = await _load_dataset_config(runtime)
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
    def __init__(self) -> None:
        super().__init__(
            key="chunking",
            requires=(products.MARKDOWN,),
            provides=(products.CHUNKS,),
        )

    async def run(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        parse_result = runtime.parse_result or {
            "markdown": ctx.require(products.MARKDOWN),
            "parse_result": None,
        }
        bundle = await _load_dataset_config(runtime)
        chunking_config = bundle.chunking if bundle is not None else None
        chunks = await runtime.services.run_chunking(
            parse_result["markdown"],
            parse_result.get("parse_result"),
            runtime.payload,
            runtime.db,
            chunking_config,
        )
        runtime.chunks = chunks
        ctx.set(products.CHUNKS, chunks)
        return _chunks_ref(runtime.payload, chunks)

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        runtime = _runtime(ctx)
        chunks = await runtime.services.load_all_chunks_from_db(runtime.payload, runtime.db)
        if not chunks:
            raise RuntimeError("workflow demo restore failed: chunk set is empty")
        runtime.chunks = chunks
        ctx.set(products.CHUNKS, chunks)


class DenseVectorizingNode(WorkflowNode):
    def __init__(self) -> None:
        super().__init__(
            key="dense_vectorizing",
            requires=(products.CHUNKS,),
            provides=(products.DENSE_VECTORS,),
        )

    async def run(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        chunks = list(ctx.require(products.CHUNKS) or [])
        vector_result = await runtime.services.store_chunk_vectors(
            chunks,
            runtime.payload,
            runtime.db,
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
    def __init__(self) -> None:
        super().__init__(
            key="pretokenize",
            requires=(products.CHUNKS,),
            provides=(products.TOKENS,),
        )

    async def run(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        plan, reason = await runtime.services.build_pretokenize_plan(runtime.payload, runtime.db)
        if reason is not None:
            raise RuntimeError(reason)
        runtime.plan = plan
        ctx.set(products.TOKENS, plan)
        return _plan_ref(runtime.payload, plan)

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        runtime = _runtime(ctx)
        plan, reason = await runtime.services.build_pretokenize_plan(runtime.payload, runtime.db)
        if reason is not None:
            raise RuntimeError(reason)
        runtime.plan = plan
        ctx.set(products.TOKENS, plan)


class EsIndexingNode(WorkflowNode):
    def __init__(self) -> None:
        super().__init__(
            key="es_indexing",
            requires=(products.TOKENS,),
            provides=(products.ES_INDEX,),
        )

    async def run(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        plan = runtime.plan or ctx.require(products.TOKENS)
        es_result = await runtime.services.run_es_indexing(plan, runtime.db)
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
    def __init__(self) -> None:
        super().__init__(
            key="sparse_vectorizing",
            requires=(products.DENSE_VECTORS,),
            provides=(products.SPARSE_VECTORS,),
        )

    async def run(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        await runtime.services.run_sparse_vectorizing(runtime.payload, runtime.db)
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


async def _load_dataset_config(runtime: ParseWorkflowRuntime):
    user_id = coerce_optional_int(runtime.payload.user_id)
    dataset_id = coerce_optional_int(runtime.payload.dataset_id)
    if user_id is None or dataset_id is None:
        return None
    return await DatasetConfigService().get_config(user_id, dataset_id, runtime.db)


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
