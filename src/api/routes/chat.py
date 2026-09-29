"""B6 Java-compatible conversation and reference-detail endpoints."""

from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.management_auth import CurrentUser, require_login
from src.api.management_http import ApiResult, ManagementRouter, success
from src.application import chat_service
from src.core.storage.document_visibility import document_original_file_table
from src.database import get_db
from src.models.chunk_record import ChunkRecordDB

router = ManagementRouter(prefix="/api/v1/chat/conversations", tags=["chat"])
chunk_router = ManagementRouter(prefix="/api/v1/knowledge/chunks", tags=["knowledge"])


class CreateConversationRequest(BaseModel):
    datasetId: int = Field(gt=0)
    title: str | None = Field(default=None, max_length=255)
    lastConfigId: int | None = Field(default=None, gt=0)


class UpdateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    isPinned: bool | None = None


class BatchChunkDetailRequest(BaseModel):
    chunkIds: list[str] = Field(min_length=1, max_length=100)


@router.post("")
async def create_conversation(
    body: CreateConversationRequest,
    user: Annotated[CurrentUser, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResult[dict]:
    data = await chat_service.create_conversation(
        db, user.user_id, body.datasetId, body.title, body.lastConfigId
    )
    await db.commit()
    return success(data)


@router.get("")
async def list_conversations(
    user: Annotated[CurrentUser, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=100),
) -> ApiResult[dict]:
    return success(await chat_service.list_conversations(db, user.user_id, page, pageSize))


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: int,
    user: Annotated[CurrentUser, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=50, ge=1, le=100),
) -> ApiResult[dict]:
    return success(
        await chat_service.list_messages(db, user.user_id, conversation_id, page, pageSize)
    )


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: int,
    body: UpdateConversationRequest,
    user: Annotated[CurrentUser, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResult[dict]:
    data = await chat_service.update_conversation(
        db, user.user_id, conversation_id, body.title, body.isPinned
    )
    await db.commit()
    return success(data)


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    user: Annotated[CurrentUser, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResult[None]:
    await chat_service.delete_conversation(db, user.user_id, conversation_id)
    await db.commit()
    return success(None)


@chunk_router.post("/batch")
async def batch_chunk_details(
    body: BatchChunkDetailRequest,
    user: Annotated[CurrentUser, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResult[list[dict]]:
    chunk_ids = list(dict.fromkeys(value.strip() for value in body.chunkIds if value.strip()))
    if not chunk_ids:
        return success([])
    rows = (
        await db.scalars(
            select(ChunkRecordDB).where(
                ChunkRecordDB.chunk_id.in_(chunk_ids),
                ChunkRecordDB.user_id == user.user_id,
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
                    document_original_file_table.c.user_id == user.user_id,
                )
            )
        ).all()
        filenames = dict((int(row[0]), str(row[1])) for row in filename_rows)
    return success(
        [
            {
                "chunkId": chunk_id,
                "documentId": chunks[chunk_id].doc_id,
                "fileName": filenames.get(chunks[chunk_id].doc_id)
                or f"文档 #{chunks[chunk_id].doc_id}",
                "content": chunks[chunk_id].content,
                "score": None,
            }
            for chunk_id in chunk_ids
            if chunk_id in chunks
        ]
    )
