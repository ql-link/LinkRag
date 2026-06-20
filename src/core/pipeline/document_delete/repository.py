"""删除链路的解析表枚举/删除仓库（LINK-55）。

只负责 ``document_parse_file`` / ``document_parsed_log`` / ``document_parse_pipeline``
三张解析表的查询与删除；chunk 真值行（``kb_document_chunk``）由 ``ChunkRepository``
负责。所有删除按 id 删，天然幂等。
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.parse_task import (
    DocumentParsedLog,
    DocumentParsePipeline,
    DocumentParseTask,
)


class ParseDeleteRepository:
    """解析表删除/枚举仓库。"""

    async def list_doc_ids_by_dataset(
        self,
        db: AsyncSession,
        dataset_id: int,
        user_id: int,
        *,
        limit: int,
    ) -> list[int]:
        """分页枚举数据集名下原文件 id（``document_original_file_id``）。

        以 ``document_parse_file`` 为权威源（Python 自有解析登记表）；带 ``user_id``
        兜底防越权。删除编排逐页处理：每删完一页对应行即消失，故下一页恒取表头
        （调用方按 limit 反复取到空为止），无需 offset。
        """
        stmt = (
            select(DocumentParseTask.document_original_file_id)
            .where(DocumentParseTask.dataset_id == dataset_id)
            .where(DocumentParseTask.user_id == user_id)
            .order_by(DocumentParseTask.id)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return [int(doc_id) for doc_id in result.scalars().all()]

    async def list_parsed_oss_keys_by_doc_id(
        self,
        db: AsyncSession,
        doc_id: int,
    ) -> list[tuple[str | None, str | None]]:
        """返回某文档全部 parsed_log 行的 ``(parsed_bucket_name, parsed_object_key)``。

        删除编排据此取解析任务目录前缀清理 OSS（Markdown + 图片同目录）。透传 md 行的
        key 指向原文件对象，由编排层按"非 parsed/ 前缀跳过"护栏排除。
        """
        stmt = select(
            DocumentParsedLog.parsed_bucket_name,
            DocumentParsedLog.parsed_object_key,
        ).where(DocumentParsedLog.document_original_file_id == doc_id)
        result = await db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def delete_parse_rows_by_doc_id(
        self,
        db: AsyncSession,
        doc_id: int,
    ) -> dict[str, int]:
        """硬删某文档的解析三表行（pipeline → parsed_log → parse_file）。

        调用方应在同一事务内、在外部存储（Qdrant/ES/OSS）清理成功之后调用，最后
        ``commit``，保证"外部产物先删、DB 账本后删"的崩溃安全次序。按 id 删，重复执行
        为 no-op。
        """
        pipeline_rows = await db.execute(
            delete(DocumentParsePipeline).where(
                DocumentParsePipeline.document_original_file_id == doc_id
            )
        )
        log_rows = await db.execute(
            delete(DocumentParsedLog).where(
                DocumentParsedLog.document_original_file_id == doc_id
            )
        )
        file_rows = await db.execute(
            delete(DocumentParseTask).where(
                DocumentParseTask.document_original_file_id == doc_id
            )
        )
        return {
            "document_parse_pipeline": int(pipeline_rows.rowcount or 0),
            "document_parsed_log": int(log_rows.rowcount or 0),
            "document_parse_file": int(file_rows.rowcount or 0),
        }
