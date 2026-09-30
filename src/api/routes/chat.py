"""B6 Java-compatible conversation and reference-detail endpoints."""

from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.management_auth import CurrentUser, require_login
from src.api.management_http import ApiResult, ManagementRouter, success
from src.application import chat_service
from src.application.chunk_details import load_owned_chunk_details
from src.application.document_files import owned_file
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


@chunk_router.get("")
async def list_file_chunks(
    user: Annotated[CurrentUser, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
    fileId: int = Query(gt=0),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
) -> ApiResult[dict]:
    """按文件分页列出有效分块（按 chunk_index 顺序），供文件详情页查看解析结果。"""
    await owned_file(db, user.user_id, fileId)
    conditions = (
        ChunkRecordDB.doc_id == fileId,
        ChunkRecordDB.user_id == user.user_id,
        ChunkRecordDB.lifecycle_status == "ACTIVE",
    )
    total = int(
        (
            await db.execute(select(func.count()).select_from(ChunkRecordDB).where(*conditions))
        ).scalar_one()
    )
    rows = (
        await db.scalars(
            select(ChunkRecordDB)
            .where(*conditions)
            .order_by(
                ChunkRecordDB.chunk_index.is_(None), ChunkRecordDB.chunk_index, ChunkRecordDB.id
            )
            .limit(pageSize)
            .offset((page - 1) * pageSize)
        )
    ).all()
    return success(
        {
            "items": [
                {
                    "chunkId": row.chunk_id,
                    "fileId": row.doc_id,
                    "datasetId": row.set_id,
                    "index": row.chunk_index,
                    "chunkType": row.chunk_type,
                    "startLine": row.start_line,
                    "endLine": row.end_line,
                    "content": row.content,
                    "updatedAt": row.update_time,
                }
                for row in rows
            ],
            "total": total,
            "page": page,
            "pageSize": pageSize,
            "totalPages": (total + pageSize - 1) // pageSize,
        }
    )


@chunk_router.post("/batch")
async def batch_chunk_details(
    body: BatchChunkDetailRequest,
    user: Annotated[CurrentUser, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResult[list[dict]]:
    details = await load_owned_chunk_details(db, user.user_id, body.chunkIds)
    return success([item | {"score": None} for item in details])
