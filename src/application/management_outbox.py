"""Durable B5 publish ledger; transport remains the existing MQService."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db_context, write_transaction
from src.observability.audit import audit_event
from src.services.mq_service import MQService


async def enqueue(
    db: AsyncSession,
    *,
    topic: str,
    payload: dict,
    key: str | None,
    event_key: str | None = None,
) -> str:
    """Call inside the same transaction that changes the business record."""
    identity = event_key or str(uuid4())
    await db.execute(
        text("""
        INSERT INTO management_mq_outbox
          (event_key,topic,message_body,message_key,status,attempt_count,next_attempt_at)
        VALUES(:event_key,:topic,:body,:message_key,'PENDING',0,NOW())
        ON DUPLICATE KEY UPDATE event_key=event_key
    """),
        {
            "event_key": identity,
            "topic": topic,
            "body": json.dumps(payload, ensure_ascii=False),
            "message_key": key,
        },
    )
    return identity


async def publish_one(event_key: str, *, mq: MQService | None = None) -> bool:
    """Claim with a lease; a lost broker ACK may duplicate the same business ID."""
    async with write_transaction() as db:
        claimed = await db.execute(
            text("""
            UPDATE management_mq_outbox
            SET status='CLAIMED',attempt_count=attempt_count+1,
                next_attempt_at=DATE_ADD(NOW(),INTERVAL 5 MINUTE)
            WHERE event_key=:event_key AND status IN ('PENDING','CLAIMED')
              AND next_attempt_at<=NOW()
        """),
            {"event_key": event_key},
        )
        if not cast(CursorResult[Any], claimed).rowcount:
            return False
        row = (
            (
                await db.execute(
                    text("""
            SELECT topic,message_body,message_key FROM management_mq_outbox
            WHERE event_key=:event_key
        """),
                    {"event_key": event_key},
                )
            )
            .mappings()
            .one()
        )
    try:
        await (mq or MQService()).send_raw(
            row["topic"], row["message_body"], key=row["message_key"]
        )
    except Exception:
        async with write_transaction() as db:
            await db.execute(
                text("""
                UPDATE management_mq_outbox
                SET status='PENDING',next_attempt_at=DATE_ADD(NOW(),INTERVAL 30 SECOND)
                WHERE event_key=:event_key AND status='CLAIMED'
            """),
                {"event_key": event_key},
            )
        audit_event("MANAGEMENT_MQ_OUTBOX", "failed")
        return False
    async with write_transaction() as db:
        await db.execute(
            text("""
            UPDATE management_mq_outbox SET status='SENT',sent_at=NOW()
            WHERE event_key=:event_key AND status='CLAIMED'
        """),
            {"event_key": event_key},
        )
    return True


async def publish_due(*, mq: MQService | None = None, limit: int = 100) -> int:
    async with get_db_context() as db:
        rows = (
            (
                await db.execute(
                    text("""
            SELECT event_key FROM management_mq_outbox
            WHERE status IN ('PENDING','CLAIMED') AND next_attempt_at<=NOW()
            ORDER BY id LIMIT :limit
        """),
                    {"limit": limit},
                )
            )
            .scalars()
            .all()
        )
    sent = 0
    for event_key in rows:
        if await publish_one(event_key, mq=mq):
            sent += 1
    return sent
