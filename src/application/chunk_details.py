"""按用户回读 chunk 正文与来源文件名。

召回结果只含 ``chunk_id``；正文以 MySQL ``kb_document_chunk`` 为真值，并按 ``user_id``
与 ``lifecycle_status='ACTIVE'`` 过滤，杜绝通过猜测 chunk_id 越权读取。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.storage.document_visibility import document_original_file_table
from src.models.chunk_record import ChunkRecordDB


async def load_owned_chunk_details(
    db: AsyncSession, user_id: int, chunk_ids: list[str]
) -> list[dict]:
    """按输入顺序返回属于 ``user_id`` 的 ACTIVE、非空 chunk；去重、跳过不可见项。"""

    ordered = list(dict.fromkeys(value.strip() for value in chunk_ids if value.strip()))
    if not ordered:
        return []
    rows = (
        await db.scalars(
            select(ChunkRecordDB).where(
                ChunkRecordDB.chunk_id.in_(ordered),
                ChunkRecordDB.user_id == user_id,
                ChunkRecordDB.lifecycle_status == "ACTIVE",
            )
        )
    ).all()
    chunks = {row.chunk_id: row for row in rows if row.content and row.content.strip()}
    doc_ids = {row.doc_id for row in chunks.values()}
    filenames: dict[int, str] = {}
    if doc_ids:
        filename_rows = (
            await db.execute(
                select(
                    document_original_file_table.c.id,
                    document_original_file_table.c.original_filename,
                ).where(
                    document_original_file_table.c.id.in_(doc_ids),
                    document_original_file_table.c.user_id == user_id,
                )
            )
        ).all()
        filenames = dict((int(row[0]), str(row[1])) for row in filename_rows)
    return [
        {
            "chunkId": chunk_id,
            "documentId": chunks[chunk_id].doc_id,
            "fileName": filenames.get(chunks[chunk_id].doc_id)
            or f"文档 #{chunks[chunk_id].doc_id}",
            "content": chunks[chunk_id].content,
        }
        for chunk_id in ordered
        if chunk_id in chunks
    ]
