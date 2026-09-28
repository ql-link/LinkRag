"""B3 admin candidate refresh, review and publish routes."""

from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel, Field

from src.api.management_auth import CurrentUser, require_role
from src.api.management_http import BusinessError, ManagementRouter, success
from src.application import model_sync
from src.config import settings

router = ManagementRouter(prefix="/api/v1/admin", tags=["admin-model-sync"])
Admin = Annotated[CurrentUser, Depends(require_role("ADMIN"))]


def _write_ready() -> None:
    if not settings.B3_CONTROL_WRITES_ENABLED:
        raise BusinessError(503, "模型目录同步写入尚未切流", 503)


class RefreshBody(BaseModel):
    syncSource: str | None = None


class PublishBody(BaseModel):
    modelName: str | None = Field(default=None, max_length=128)
    displayName: str | None = Field(default=None, max_length=64)
    capability: str | None = Field(default=None, max_length=32)
    protocol: str | None = Field(default=None, max_length=32)
    apiBaseUrl: str | None = Field(default=None, max_length=512)


class BulkPublishBody(BaseModel):
    candidateIds: list[int] = Field(min_length=1)
    modelName: str | None = Field(default=None, max_length=128)
    displayName: str | None = Field(default=None, max_length=64)


class ReviewBody(BaseModel):
    reviewStatus: str = Field(min_length=1, max_length=16)


@router.post("/providers/{provider_id}/model-sync")
async def refresh(provider_id: int, admin: Admin, body: RefreshBody | None = None):
    _write_ready()
    return success(await model_sync.refresh(
        provider_id, body.syncSource if body else None, admin.user_id
    ))


@router.get("/model-sync-jobs")
async def jobs(
    admin: Admin, page: int = Query(1, ge=1), size: int = Query(10, ge=1, le=100),
    providerId: int | None = None, syncSource: str | None = None,
    status: str | None = None,
):
    return success(await model_sync.list_jobs(page, size, providerId, syncSource, status))


@router.get("/model-sync-candidates")
async def candidates(
    admin: Admin, page: int = Query(1, ge=1), size: int = Query(10, ge=1, le=100),
    providerId: int | None = None, jobId: int | None = None,
    reviewStatus: str | None = None, capability: str | None = None,
):
    return success(await model_sync.list_candidates(
        page, size, providerId, jobId, reviewStatus, capability
    ))


@router.post("/model-sync-candidates/{candidate_id}/publish")
async def publish_one(candidate_id: int, admin: Admin, body: PublishBody | None = None):
    _write_ready()
    result = await model_sync.publish(
        [candidate_id], body.model_dump(exclude_none=True) if body else {}, admin.user_id
    )
    return success(result[0])


@router.post("/model-sync-candidates/publish")
async def publish_many(body: BulkPublishBody, admin: Admin):
    _write_ready()
    return success(await model_sync.publish(
        body.candidateIds, body.model_dump(exclude_none=True, exclude={"candidateIds"}),
        admin.user_id,
    ))


@router.patch("/model-sync-candidates/{candidate_id}/review")
async def review(candidate_id: int, body: ReviewBody, admin: Admin):
    _write_ready()
    return success(await model_sync.review(candidate_id, body.reviewStatus, admin.user_id))
