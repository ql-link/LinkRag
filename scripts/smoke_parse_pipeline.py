"""端到端冒烟测试：直跑 ParseTaskPipeline.execute()。

不经 Kafka，直接在进程内构造 ParseTaskPayload 并 await execute()，
真实写入 MinIO / MySQL / Qdrant / ES。

用法:
    .venv/bin/python scripts/smoke_parse_pipeline.py [--backend docling|mineru] [--keep]

默认 backend=mineru（依赖 MinerU 公网 API 拉取 MinIO URL）。
--keep 表示保留测试产物（默认会清理）。
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import time
import uuid
from pathlib import Path

# 将仓库根加入 sys.path，便于在 worktree 内独立运行。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from sqlalchemy import delete

from src.config import settings
from src.core.mq.messages.parse_task import ParseTaskMessage
from src.core.pipeline import ParseTaskPipeline, PipelineStatus
from src.database import get_async_session_factory
from src.models.parse_task import (
    DocumentParsedLog,
    DocumentParseTask,
    DocumentPostProcessPipeline,
)
from src.services.storage.factory import StorageFactory


# 用大数字 + 随机后缀，避免和真实业务行冲突。
_TEST_ID_BASE = 9_900_000


def build_test_pdf(title: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, 720, title)
    c.setFont("Helvetica", 12)
    lines = [
        "This is an end-to-end smoke test for ParseTaskPipeline.",
        "We are validating: storage download/upload, parser, chunking,",
        "vector indexing, ES indexing, and parse_result notification.",
        "",
        "Section 1: Background",
        "RAG pipelines benefit from semantic chunking and retrieval over",
        "vector + lexical indexes. This document exercises both paths.",
        "",
        "Section 2: Verification points",
        "- document_parsed_log row reaches success terminal state.",
        "- document_post_process_pipeline row reaches SUCCESS.",
        "- ParseResultMessage emitted with task_status=success.",
    ]
    y = 690
    for line in lines:
        c.drawString(72, y, line)
        y -= 18
    c.save()
    return buf.getvalue()


async def insert_parse_task_row(
    parse_task_id: int,
    file_id: int,
    user_id: int,
    dataset_id: int,
    task_id: str,
    filename: str,
) -> None:
    factory = get_async_session_factory()
    async with factory() as db:
        row = DocumentParseTask(
            id=parse_task_id,
            document_original_file_id=file_id,
            dataset_id=dataset_id,
            user_id=user_id,
            latest_parse_task_id=task_id,
            original_filename=filename,
            parse_count=1,
        )
        db.add(row)
        await db.commit()
        logger.info(f"inserted DocumentParseTask id={parse_task_id}")


async def cleanup(
    parse_task_id: int,
    task_id: str,
    storage,
    src_bucket: str,
    src_key: str,
    md_bucket: str,
    md_key: str,
) -> None:
    factory = get_async_session_factory()
    async with factory() as db:
        await db.execute(
            delete(DocumentPostProcessPipeline).where(
                DocumentPostProcessPipeline.task_id == task_id
            )
        )
        await db.execute(
            delete(DocumentParsedLog).where(DocumentParsedLog.task_id == task_id)
        )
        await db.execute(
            delete(DocumentParseTask).where(DocumentParseTask.id == parse_task_id)
        )
        await db.commit()
        logger.info(f"cleaned DB rows for task_id={task_id}")

    s3 = getattr(storage, "_client", None)
    for bucket, key in [(src_bucket, src_key), (md_bucket, md_key)]:
        if s3 is None:
            continue
        try:
            s3.delete_object(Bucket=bucket, Key=key)
            logger.info(f"deleted {bucket}/{key}")
        except Exception as exc:
            logger.warning(f"failed to delete {bucket}/{key}: {exc}")


def _fmt_ms(ms: int | float | None) -> str:
    if ms is None:
        return "    -    "
    if ms >= 1000:
        return f"{ms / 1000:>7.2f} s"
    return f"{int(ms):>5d} ms "


def print_timing_report(stage_timings: list[tuple[str, int | None]], total_wall_ms: int) -> None:
    """打印阶段耗时汇总表。"""
    header = f"{'Stage':<32} {'Duration':>11}"
    print()
    print("=" * 50)
    print("解析流程阶段耗时")
    print("=" * 50)
    print(header)
    print("-" * 50)
    for name, ms in stage_timings:
        print(f"{name:<32} {_fmt_ms(ms):>11}")
    print("-" * 50)
    print(f"{'pipeline 端到端 (wallclock)':<32} {_fmt_ms(total_wall_ms):>11}")
    print("=" * 50)


async def main(backend: str, keep: bool) -> int:
    suffix = uuid.uuid4().hex[:8]
    task_id = f"test_{suffix}"
    parse_task_id = _TEST_ID_BASE + int(suffix, 16) % 100_000
    file_id = parse_task_id + 1
    user_id = 999_999
    dataset_id = 999_999
    src_bucket = "rag-raw"
    md_bucket = "rag-md"
    src_key = f"smoke-test/{task_id}.pdf"
    md_key = f"smoke-test/{task_id}.md"
    filename = f"{task_id}.pdf"

    logger.info(
        f"smoke-test params: task_id={task_id} parse_task_id={parse_task_id} "
        f"file_id={file_id} backend={backend}"
    )

    # ===== 阶段 1：脚本侧准备 =====
    storage = StorageFactory.get_storage()
    t = time.time()
    pdf_bytes = build_test_pdf(f"Smoke Test {task_id}")
    pdf_gen_ms = int((time.time() - t) * 1000)

    t = time.time()
    storage.upload_bytes(
        bucket=src_bucket,
        object_key=src_key,
        content=pdf_bytes,
        content_type="application/pdf",
    )
    upload_src_ms = int((time.time() - t) * 1000)
    logger.info(f"uploaded test PDF to {src_bucket}/{src_key} ({len(pdf_bytes)} bytes)")

    t = time.time()
    await insert_parse_task_row(
        parse_task_id=parse_task_id,
        file_id=file_id,
        user_id=user_id,
        dataset_id=dataset_id,
        task_id=task_id,
        filename=filename,
    )
    insert_row_ms = int((time.time() - t) * 1000)

    # ===== 阶段 2：调用 pipeline =====
    payload = ParseTaskMessage.build(
        task_id=task_id,
        original_file_id=file_id,
        document_parse_task_id=parse_task_id,
        user_id=user_id,
        dataset_id=dataset_id,
        file_type="pdf",
        source_bucket=src_bucket,
        source_object_key=src_key,
        source_filename=filename,
        md_bucket=md_bucket,
        md_object_key=md_key,
        pdf_parser_backend=backend,
        image_bucket=md_bucket,
        image_prefix=f"smoke-test/{task_id}/images",
    ).get_payload()

    pipeline = ParseTaskPipeline()
    t0 = time.time()
    try:
        result = await pipeline.execute(payload)
    finally:
        wall_ms = int((time.time() - t0) * 1000)

    logger.info(f"pipeline result: {result}")
    exit_code = 0
    if result.status == PipelineStatus.SUCCESS:
        logger.success(
            f"SUCCESS: chunks={result.chunk_count} "
            f"parse_engine_time_cost_ms={result.time_cost_ms} pages={result.page_count}"
        )
    else:
        logger.error(f"FAILED: status={result.status.value} error={result.error}")
        exit_code = 1

    # ===== 阶段 3：从 DB 回读各 stage 耗时 =====
    factory = get_async_session_factory()
    async with factory() as db:
        from sqlalchemy import select

        log = (
            await db.execute(
                select(DocumentParsedLog).where(DocumentParsedLog.task_id == task_id)
            )
        ).scalar_one_or_none()
        pp = (
            await db.execute(
                select(DocumentPostProcessPipeline).where(
                    DocumentPostProcessPipeline.task_id == task_id
                )
            )
        ).scalar_one_or_none()
        logger.info(
            f"DB state: parsed_log.task_status={log.task_status if log else None} "
            f"failure_reason={getattr(log, 'failure_reason', None)} | "
            f"post_process.pipeline_status="
            f"{getattr(pp, 'pipeline_status', None)} "
            f"chunking={getattr(pp, 'chunking_status', None)} "
            f"vectorizing={getattr(pp, 'vectorizing_status', None)} "
            f"es={getattr(pp, 'es_indexing_status', None)} "
            f"chunk_count={getattr(pp, 'chunk_count', None)}"
        )

    # 组装阶段表
    parse_ms = getattr(log, "parse_duration_ms", None) if log else None
    chunking_ms = getattr(pp, "chunking_duration_ms", None) if pp else None
    vectorizing_ms = getattr(pp, "vectorizing_duration_ms", None) if pp else None
    es_ms = getattr(pp, "es_indexing_duration_ms", None) if pp else None
    post_total_ms = getattr(pp, "total_duration_ms", None) if pp else None

    # parse 引擎自身耗时（不含上传 Markdown）
    engine_ms = result.time_cost_ms if result.status == PipelineStatus.SUCCESS else None

    stage_timings: list[tuple[str, int | None]] = [
        ("[script] 生成测试 PDF", pdf_gen_ms),
        ("[script] 上传源 PDF 到 MinIO", upload_src_ms),
        ("[script] 插入 document_parse_file 行", insert_row_ms),
        (f"[pipeline] 解析+上传 markdown (parse_*)", parse_ms),
        (f"  └─ 解析引擎本身 ({backend})", engine_ms),
        ("[pipeline] chunking", chunking_ms),
        ("[pipeline] vectorizing (embed + Qdrant)", vectorizing_ms),
        ("[pipeline] es_indexing", es_ms),
        ("[pipeline] post_process 合计", post_total_ms),
    ]
    print_timing_report(stage_timings, wall_ms)

    if keep:
        logger.warning(f"--keep set, leaving test data for inspection (task_id={task_id})")
    else:
        await cleanup(
            parse_task_id=parse_task_id,
            task_id=task_id,
            storage=storage,
            src_bucket=src_bucket,
            src_key=src_key,
            md_bucket=md_bucket,
            md_key=md_key,
        )

    return exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["mineru", "docling"], default="mineru")
    parser.add_argument("--keep", action="store_true", help="保留 DB / MinIO 测试产物")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.backend, args.keep)))
