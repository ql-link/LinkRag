"""B7 用量查询端点。"""

from datetime import date
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.management_auth import CurrentUser, require_login
from src.api.management_http import ApiResult, ManagementRouter, success
from src.application import usage_ledger
from src.database import get_db

router = ManagementRouter(prefix="/api/v1/llm/usage", tags=["usage"])
User = Annotated[CurrentUser, Depends(require_login)]
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/summary")
async def summary(startDate: date, endDate: date, user: User, db: DB,
                  stage: str = "chat") -> ApiResult[dict]:
    return success(await usage_ledger.summary(db, user.user_id, startDate, endDate, stage))


@router.get("/daily")
async def daily(startDate: date, endDate: date, user: User, db: DB,
                stage: str = "chat") -> ApiResult[list[dict]]:
    return success(await usage_ledger.daily(db, user.user_id, startDate, endDate, stage))


@router.get("/logs")
async def logs(startDate: date, endDate: date, user: User, db: DB,
               stage: str = "chat", page: int = Query(1, ge=1),
               pageSize: int = Query(20, ge=1, le=200)) -> ApiResult[dict]:
    return success(await usage_ledger.logs(db, user.user_id, startDate, endDate, stage, page, pageSize))


@router.get("/by-model")
async def by_model(startDate: date, endDate: date, user: User, db: DB) -> ApiResult[list[dict]]:
    return success(await usage_ledger.by_model(db, user.user_id, startDate, endDate))


@router.get("/trend")
async def trend(startDate: date, endDate: date, user: User, db: DB) -> ApiResult[dict]:
    return success(await usage_ledger.trend(db, user.user_id, startDate, endDate))
