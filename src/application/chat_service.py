"""B6 conversation operations and durable chat-turn projection."""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.management_http import BusinessError
from src.application.model_configs import require_executable
from src.core.mq.messages.chat_turn import ChatTurnPayload
from src.core.storage.document_visibility import dataset_table
from src.models.db_models import ChatConversationDB, ChatMessageDB

DEFAULT_TITLE = "新对话"


def _now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)


def _page(items: list[dict], total: int, page: int, page_size: int) -> dict:
    return {
        "items": items,
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size,
    }


def _conversation(row: ChatConversationDB) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "datasetId": row.dataset_id,
        "lastConfigId": row.last_config_id,
        "lastModelName": row.last_model_name,
        "isPinned": row.is_pinned,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
    }


def _message(row: ChatMessageDB) -> dict:
    return {
        "id": row.id,
        "conversationId": row.conversation_id,
        "turnId": row.turn_id,
        "query": row.query,
        "answer": row.answer,
        "configId": row.config_id,
        "modelName": row.model_name,
        "references": row.references,
        "requestId": row.request_id,
        "status": row.status,
        "errorCode": row.error_code,
        "errorMessage": row.error_message,
        "createdAt": row.created_at,
    }


async def owned_conversation(
    db: AsyncSession, user_id: int, conversation_id: int, *, lock: bool = False
) -> ChatConversationDB:
    query = select(ChatConversationDB).where(
        ChatConversationDB.id == conversation_id,
        ChatConversationDB.user_id == user_id,
    )
    if lock:
        query = query.with_for_update()
    row = (await db.execute(query)).scalar_one_or_none()
    if row is None:
        raise BusinessError(404, "对话不存在", 404)
    return row


async def create_conversation(
    db: AsyncSession,
    user_id: int,
    dataset_id: int,
    title: str | None,
    config_id: int | None,
) -> dict:
    dataset = await db.scalar(
        select(dataset_table.c.id).where(
            dataset_table.c.id == dataset_id,
            dataset_table.c.user_id == user_id,
        )
    )
    if dataset is None:
        raise BusinessError(404, "数据集不存在或无权访问", 404)
    if config_id is not None:
        await require_executable(db, user_id, config_id, "CHAT")
    row = ChatConversationDB(
        user_id=user_id,
        dataset_id=dataset_id,
        title=title if title is not None else DEFAULT_TITLE,
        last_config_id=config_id,
        is_pinned=False,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return _conversation(row)


async def list_conversations(db: AsyncSession, user_id: int, page: int, page_size: int) -> dict:
    where = ChatConversationDB.user_id == user_id
    total = await db.scalar(select(func.count()).select_from(ChatConversationDB).where(where))
    rows = (
        await db.scalars(
            select(ChatConversationDB)
            .where(where)
            .order_by(
                ChatConversationDB.is_pinned.desc(),
                ChatConversationDB.updated_at.desc(),
                ChatConversationDB.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return _page([_conversation(row) for row in rows], total or 0, page, page_size)


async def list_messages(
    db: AsyncSession, user_id: int, conversation_id: int, page: int, page_size: int
) -> dict:
    await owned_conversation(db, user_id, conversation_id)
    where = ChatMessageDB.conversation_id == conversation_id
    total = await db.scalar(select(func.count()).select_from(ChatMessageDB).where(where))
    rows = (
        await db.scalars(
            select(ChatMessageDB)
            .where(where)
            .order_by(ChatMessageDB.created_at.asc(), ChatMessageDB.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return _page([_message(row) for row in rows], total or 0, page, page_size)


async def update_conversation(
    db: AsyncSession,
    user_id: int,
    conversation_id: int,
    title: str | None,
    is_pinned: bool | None,
) -> dict:
    row = await owned_conversation(db, user_id, conversation_id, lock=True)
    if title is None and is_pinned is None:
        raise BusinessError(400, "请至少提供一个需要更新的字段", 400)
    if title is not None:
        title = title.strip()
        if not title:
            raise BusinessError(400, "对话标题不能为空", 400)
        row.title = title
    if is_pinned is not None:
        row.is_pinned = is_pinned
    row.updated_at = _now()
    await db.flush()
    return _conversation(row)


async def delete_conversation(db: AsyncSession, user_id: int, conversation_id: int) -> None:
    row = await owned_conversation(db, user_id, conversation_id, lock=True)
    await db.execute(delete(ChatMessageDB).where(ChatMessageDB.conversation_id == row.id))
    await db.delete(row)


# 终态：落库后不再被重放覆盖。STOPPED 为用户主动停止生成（保留半截答案）。
TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED", "STOPPED"})


async def persist_chat_turn(db: AsyncSession, payload: ChatTurnPayload) -> bool:
    """Serialize by conversation row; terminal turns never regress on replay."""
    try:
        conversation = await owned_conversation(
            db, payload.user_id, payload.conversation_id, lock=True
        )
    except BusinessError:
        return False
    # The DB index is globally unique, even though the business lookup includes conversation_id.
    existing = (
        await db.execute(select(ChatMessageDB).where(ChatMessageDB.turn_id == payload.turn_id))
    ).scalar_one_or_none()
    if existing is not None and existing.conversation_id != conversation.id:
        return False
    if existing is not None and existing.status in TERMINAL_STATUSES:
        return True
    if existing is not None and payload.status == "GENERATING":
        return True
    if existing is None:
        existing = ChatMessageDB(conversation_id=conversation.id, turn_id=payload.turn_id)
        db.add(existing)
        existing.query = payload.query
        existing.created_at = _now()
    existing.config_id = payload.config_id
    existing.model_name = payload.model_name or existing.model_name
    existing.answer = payload.answer
    existing.references = payload.references
    existing.request_id = payload.request_id
    existing.status = payload.status
    existing.error_code = payload.error_code
    existing.error_message = payload.error_message
    conversation.last_config_id = payload.config_id
    if payload.model_name:
        conversation.last_model_name = payload.model_name
    title = re.sub(r"\s+", " ", (payload.title or "").strip())[:255]
    if title and (not conversation.title or conversation.title.strip() in {DEFAULT_TITLE, title}):
        conversation.title = title
    conversation.updated_at = _now()
    await db.flush()
    return True
