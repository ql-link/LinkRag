"""B5 tombstones, delete notifications, and replay of missed notifications."""

from __future__ import annotations

import json

from sqlalchemy import text

from src.application.datasets import owned_dataset
from src.application.document_files import owned_file
from src.application.management_outbox import enqueue, publish_one
from src.core.mq.messages.document_delete import DocumentDeleteMessage
from src.database import get_db_context, write_transaction
from src.observability.audit import audit_event
from src.services.mq_service import MQService


async def _publish(
    delete_type: str, dataset_id: int, user_id: int,
    original_file_id: int | None = None, *, mq: MQService | None = None,
) -> None:
    message = DocumentDeleteMessage.build(
        delete_type, dataset_id, user_id, original_file_id
    )
    payload = message.get_payload().model_dump(exclude_none=True)
    payload.pop("message_id", None)
    payload.pop("timestamp", None)
    await (mq or MQService()).send_raw(
        DocumentDeleteMessage.MQ_NAME,
        json.dumps(payload, ensure_ascii=False),
        key=str(dataset_id),
    )


async def delete_file(user_id: int, file_id: int, *, mq: MQService | None = None) -> None:
    event_key = f"delete:file:{file_id}"
    async with write_transaction() as db:
        file = await owned_file(db, user_id, file_id)
        await db.execute(text("UPDATE document_original_file SET is_deleted=1,deleted_seq=id "
                              "WHERE id=:fid AND user_id=:uid AND is_deleted=0"),
                         {"fid": file_id, "uid": user_id})
        message = DocumentDeleteMessage.build("file", int(file["dataset_id"]), user_id, file_id)
        await enqueue(
            db, topic=DocumentDeleteMessage.MQ_NAME,
            payload=message.get_payload().model_dump(exclude_none=True,
                                                      exclude={"message_id", "timestamp"}),
            key=str(file["dataset_id"]), event_key=event_key,
        )
    if not await publish_one(event_key, mq=mq):
        audit_event("DOCUMENT_DELETE_NOTIFY", "failed", actor_id=user_id, target_id=file_id)
        return
    audit_event("DOCUMENT_DELETE_NOTIFY", "success", actor_id=user_id, target_id=file_id)


async def delete_dataset(user_id: int, dataset_id: int, *, mq: MQService | None = None) -> None:
    event_key = f"delete:dataset:{dataset_id}"
    async with write_transaction() as db:
        await owned_dataset(db, user_id, dataset_id)
        await db.execute(text("UPDATE document_original_file SET is_deleted=1,deleted_seq=id "
                              "WHERE dataset_id=:did AND user_id=:uid AND is_deleted=0"),
                         {"did": dataset_id, "uid": user_id})
        await db.execute(text("DELETE m FROM chat_message m "
                              "JOIN chat_conversation c ON c.id=m.conversation_id "
                              "WHERE c.dataset_id=:did AND c.user_id=:uid"),
                         {"did": dataset_id, "uid": user_id})
        await db.execute(text("DELETE FROM chat_conversation "
                              "WHERE dataset_id=:did AND user_id=:uid"),
                         {"did": dataset_id, "uid": user_id})
        await db.execute(text("UPDATE dataset SET is_deleted=1,deleted_seq=id "
                              "WHERE id=:did AND user_id=:uid AND is_deleted=0"),
                         {"did": dataset_id, "uid": user_id})
        message = DocumentDeleteMessage.build("dataset", dataset_id, user_id)
        await enqueue(
            db, topic=DocumentDeleteMessage.MQ_NAME,
            payload=message.get_payload().model_dump(exclude_none=True,
                                                      exclude={"message_id", "timestamp"}),
            key=str(dataset_id), event_key=event_key,
        )
    if not await publish_one(event_key, mq=mq):
        audit_event("DATASET_DELETE_NOTIFY", "failed", actor_id=user_id, target_id=dataset_id)
        return
    audit_event("DATASET_DELETE_NOTIFY", "success", actor_id=user_id, target_id=dataset_id)


async def replay_pending_deletions(*, mq: MQService | None = None, limit: int = 100) -> int:
    """Replay tombstones that still have parse ledger rows; consumer stays idempotent."""
    async with get_db_context() as db:
        rows = (await db.execute(text("""
            SELECT DISTINCT f.id AS file_id,f.dataset_id,f.user_id
            FROM document_original_file f
            JOIN document_parse_file pf ON pf.document_original_file_id=f.id
            LEFT JOIN dataset d ON d.id=f.dataset_id
            WHERE (f.is_deleted=1 OR d.is_deleted=1)
            ORDER BY f.id LIMIT :limit
        """), {"limit": limit})).mappings().all()
    sent = 0
    for row in rows:
        try:
            await _publish("file", int(row["dataset_id"]), int(row["user_id"]),
                           int(row["file_id"]), mq=mq)
            sent += 1
        except Exception:
            audit_event("DOCUMENT_DELETE_REPLAY", "failed", target_id=int(row["file_id"]))
    return sent
