"""B7 用量账本：本地持久化与 Java 查询口径。"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.management_http import BusinessError
from src.models.db_models import UsageLogDB


def period(start: date, end: date) -> tuple[datetime, datetime]:
    if start > end:
        raise BusinessError(400, "startDate 不能晚于 endDate", 400)
    return datetime.combine(start, time.min), datetime.combine(end, time(23, 59, 59))


def scope(user_id: int, start: datetime, end: datetime, stage: str | None = None):
    conditions = [UsageLogDB.user_id == user_id, UsageLogDB.created_at.between(start, end)]
    effective = (stage or "chat").strip() or "chat"
    if effective.lower() != "all":
        conditions.append(UsageLogDB.stage == effective)
    return conditions


def _page(items: list[dict], total: int, page: int, size: int) -> dict:
    return {"items": items, "total": total, "page": page, "pageSize": size,
            "totalPages": (total + size - 1) // size}


def _round4(numerator: int, denominator: int) -> float:
    return float((Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP))


async def summary(db: AsyncSession, user_id: int, start: date, end: date, stage: str) -> dict:
    a, b = period(start, end)
    row = (await db.execute(select(
        func.count(UsageLogDB.id), func.coalesce(func.sum(UsageLogDB.total_tokens), 0),
        func.coalesce(func.sum(UsageLogDB.prompt_tokens), 0),
        func.coalesce(func.sum(UsageLogDB.completion_tokens), 0),
        func.sum(case((func.lower(UsageLogDB.status) == "success", 1), else_=0)),
        func.avg(case((func.lower(UsageLogDB.status) == "success", UsageLogDB.latency_ms))),
    ).where(*scope(user_id, a, b, stage)))).one()
    calls, tokens, prompt, completion, successes, latency = row
    calls, successes = int(calls or 0), int(successes or 0)
    return {"totalCalls": calls, "totalTokens": int(tokens), "promptTokens": int(prompt),
            "completionTokens": int(completion), "averageLatencyMs": float(latency or 0),
            "successCalls": successes, "failedCalls": calls - successes,
            "successRate": _round4(successes, calls) if calls else 0.0}


async def daily(db: AsyncSession, user_id: int, start: date, end: date, stage: str) -> list[dict]:
    a, b = period(start, end)
    day = func.date(UsageLogDB.created_at)
    rows = (await db.execute(select(
        day, func.count(UsageLogDB.id), func.coalesce(func.sum(UsageLogDB.prompt_tokens), 0),
        func.coalesce(func.sum(UsageLogDB.completion_tokens), 0),
        func.coalesce(func.sum(UsageLogDB.total_tokens), 0),
    ).where(*scope(user_id, a, b, stage)).group_by(day).order_by(day))).all()
    return [{"date": str(d), "calls": int(c), "promptTokens": int(p),
             "completionTokens": int(q), "totalTokens": int(t)} for d, c, p, q, t in rows]


async def logs(db: AsyncSession, user_id: int, start: date, end: date,
               stage: str, page: int, size: int) -> dict:
    a, b = period(start, end)
    conditions = scope(user_id, a, b, stage)
    total = await db.scalar(select(func.count()).select_from(UsageLogDB).where(*conditions)) or 0
    rows = (await db.scalars(select(UsageLogDB).where(*conditions)
                             .order_by(UsageLogDB.created_at.desc())
                             .offset((page - 1) * size).limit(size))).all()
    return _page([{"id": r.id, "configId": r.config_id, "providerType": r.provider_type,
                   "modelName": r.model_name, "stage": r.stage, "operation": r.operation,
                   "promptTokens": r.prompt_tokens, "completionTokens": r.completion_tokens,
                   "totalTokens": r.total_tokens, "latencyMs": r.latency_ms,
                   "status": r.status, "errorMessage": r.error_message,
                   "createdAt": r.created_at} for r in rows], int(total), page, size)


async def by_model(db: AsyncSession, user_id: int, start: date, end: date) -> list[dict]:
    a, b = period(start, end)
    rows = (await db.execute(select(
        UsageLogDB.provider_type, UsageLogDB.model_name, func.count(UsageLogDB.id),
        func.coalesce(func.sum(UsageLogDB.prompt_tokens), 0),
        func.coalesce(func.sum(UsageLogDB.completion_tokens), 0),
        func.coalesce(func.sum(UsageLogDB.total_tokens), 0),
    ).where(*scope(user_id, a, b, "all"))
        .group_by(UsageLogDB.provider_type, UsageLogDB.model_name)
        .order_by(func.sum(UsageLogDB.total_tokens).desc()))).all()
    return [{"providerType": provider, "modelName": model, "calls": int(c),
             "promptTokens": int(p), "completionTokens": int(q), "totalTokens": int(t)}
            for provider, model, c, p, q, t in rows]


async def trend(db: AsyncSession, user_id: int, start: date, end: date) -> dict:
    period(start, end)
    days = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = start - timedelta(days=days)
    async def totals(a: date, b: date) -> tuple[int, int]:
        first, last = period(a, b)
        row = (await db.execute(select(func.coalesce(func.sum(UsageLogDB.total_tokens), 0),
                                       func.count(UsageLogDB.id))
                                .where(*scope(user_id, first, last, "all")))).one()
        return int(row[0]), int(row[1])
    (ct, cc), (pt, pc) = await totals(start, end), await totals(previous_start, previous_end)
    return {"currentTokens": ct, "previousTokens": pt, "currentCalls": cc,
            "previousCalls": pc, "tokenGrowthRate": _round4(ct - pt, pt) if pt else None,
            "callGrowthRate": _round4(cc - pc, pc) if pc else None}
