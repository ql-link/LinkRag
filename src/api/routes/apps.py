"""接入应用服务端 API（``/api/v1/apps/*``）。

调用方是接入应用后端（如 Link Resume），以应用凭证 + ``X-App-User-Id`` 代其用户操作。
本模块只是薄路由层：身份解析为影子 ``user_id`` 后，全部复用现有 application 函数，
数据隔离与 Web 端完全一致（按 ``user_id``）。写入开关与 Web 端共用。

总开关 ``APPS_API_ENABLED`` 关闭时全部 404；公网 nginx 对本前缀同样返回 404。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.app_auth import AppPrincipal, require_app_principal
from src.api.management_http import BusinessError, ManagementRouter, success
from src.application import datasets as dataset_service
from src.application import document_files
from src.application.app_identity import set_default_dataset
from src.application.chunk_details import load_owned_chunk_details
from src.application.document_deletion import delete_file
from src.application.document_uploads import DocumentUploadExecutor, upload
from src.application.parse_task_control import submit_parse
from src.application.recall_errors import RecallApiError
from src.application.recall_json_runtime import run_recall_json
from src.application.recall_pipeline_provider import (
    aresolve_recall_execution,
    build_recall_request_from_config,
    get_recall_pipeline,
)
from src.config import settings
from src.core.llm.exceptions import (
    DatasetModelBindingRequiredError,
    LLMConfigResolutionError,
)
from src.core.pipeline.recall import RecallPipeline
from src.core.storage.dataset_scope import resolve_user_dataset_scope
from src.database import get_db

router = ManagementRouter(prefix="/api/v1/apps", tags=["apps"])

Principal = Annotated[AppPrincipal, Depends(require_app_principal)]
DB = Annotated[AsyncSession, Depends(get_db)]

DEFAULT_DATASET_NAME = "资料库"
MAX_RECALL_FILE_IDS = 100


def _require(flag: bool, message: str) -> None:
    if not flag:
        raise BusinessError(503, message, 503)


async def _ensure_default_dataset(principal: AppPrincipal) -> int:
    """返回影子用户默认资料库；不存在（或已删除）时按应用默认 embedding 创建。"""

    if principal.default_dataset_id is not None:
        try:
            await dataset_service.detail(
                principal.user_id, principal.default_dataset_id
            )
            return principal.default_dataset_id
        except BusinessError as exc:
            if exc.http_status != 404:
                raise
    app = principal.app
    if app.default_dense_config_id is None or app.default_sparse_config_id is None:
        raise BusinessError(409, "接入应用未配置默认 embedding", 409)
    try:
        created = await dataset_service.create_dataset(
            principal.user_id,
            DEFAULT_DATASET_NAME,
            None,
            app.default_dense_config_id,
            app.default_sparse_config_id,
        )
        dataset_id = int(created["id"])
    except BusinessError as exc:
        # 并发首建：仅同名唯一键冲突（code=400）时回读；模型绑定非法（10028）等照常抛出。
        if exc.code != 400:
            raise
        dataset_id = await _dataset_id_by_name(principal.user_id, DEFAULT_DATASET_NAME)
    await set_default_dataset(principal.app_code, principal.user_id, dataset_id)
    return dataset_id


async def _dataset_id_by_name(user_id: int, name: str) -> int:
    from src.database import get_db_context

    async with get_db_context() as db:
        row = (
            await db.execute(
                text(
                    "SELECT id FROM dataset WHERE user_id=:uid AND name=:name AND is_deleted=0"
                ),
                {"uid": user_id, "name": name},
            )
        ).scalar_one_or_none()
    if row is None:
        raise BusinessError(503, "默认资料库暂不可用", 503)
    return int(row)


@router.put("/datasets/default")
async def ensure_default_dataset(principal: Principal):
    _require(settings.B4_DATASET_WRITES_ENABLED, "数据集写入尚未切流")
    dataset_id = await _ensure_default_dataset(principal)
    return success(await dataset_service.detail(principal.user_id, dataset_id))


@router.post("/files")
async def upload_file(
    request: Request,
    principal: Principal,
    file: UploadFile = File(...),
    datasetId: int | None = Form(None),
    externalRef: str | None = Form(None, max_length=128),
):
    _require(settings.B5_FILE_WRITES_ENABLED, "文件上传尚未切流")
    executor: DocumentUploadExecutor | None = getattr(
        request.app.state, "document_upload_executor", None
    )
    if executor is None:
        raise BusinessError(503, "文件上传队列尚未就绪", 503)
    if datasetId is None:
        _require(settings.B4_DATASET_WRITES_ENABLED, "数据集写入尚未切流")
        datasetId = await _ensure_default_dataset(principal)
    result = await upload(
        principal.user_id, datasetId, file, parse_immediately=True, executor=executor
    )
    return success(result | {"externalRef": externalRef})


@router.get("/files/{file_id}")
async def file_status(file_id: int, principal: Principal):
    info = await document_files.detail(principal.user_id, file_id)
    parse = (
        await document_files.parse_results(
            principal.user_id, info["datasetId"], [file_id]
        )
    )[0]
    return success(
        info
        | {
            "parseStatus": parse["parseStatus"],
            "frontendStatus": parse["frontendStatus"],
            "parseFailureReason": parse["failureReason"],
        }
    )


@router.post("/files/{file_id}/parse")
async def reparse_file(file_id: int, principal: Principal):
    _require(settings.B5_FILE_WRITES_ENABLED, "文件解析提交尚未切流")
    return success(await submit_parse(principal.user_id, file_id))


@router.delete("/files/{file_id}")
async def remove_file(file_id: int, principal: Principal):
    _require(settings.B5_DELETE_WRITES_ENABLED, "文件删除尚未切流")
    await delete_file(principal.user_id, file_id)
    return success()


class AppRecallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    datasetIds: list[int] | None = Field(default=None, max_length=20)
    fileIds: list[int] | None = Field(default=None, max_length=MAX_RECALL_FILE_IDS)
    topK: int | None = Field(default=None, ge=1, le=50)


async def _assert_owned_files(
    db: AsyncSession, user_id: int, dataset_ids: list[int], file_ids: list[int]
) -> None:
    """``fileIds`` 必须全部属于当前用户且落在召回数据集内；否则整体 403，不静默过滤。"""

    rows = await db.execute(
        text(
            "SELECT id FROM document_original_file "
            "WHERE id IN :fids AND user_id=:uid AND dataset_id IN :dids AND is_deleted=0"
        ).bindparams(
            bindparam("fids", expanding=True), bindparam("dids", expanding=True)
        ),
        {"fids": file_ids, "uid": user_id, "dids": dataset_ids},
    )
    if {int(row[0]) for row in rows} != set(file_ids):
        raise BusinessError(403, "文件不存在或无权访问", 403)


@router.post("/recall")
async def recall(
    body: AppRecallRequest,
    principal: Principal,
    db: DB,
    pipeline: Annotated[RecallPipeline, Depends(get_recall_pipeline)],
):
    if not body.query.strip():
        raise BusinessError(400, "query 不能为空", 400)
    try:
        dataset_ids = await resolve_user_dataset_scope(
            db, user_id=principal.user_id, requested_dataset_ids=body.datasetIds
        )
    except RecallApiError as exc:
        raise BusinessError(exc.status_code, exc.message, exc.status_code) from exc
    if not dataset_ids:
        return success({"hits": [], "failedSources": []})
    file_ids = list(dict.fromkeys(body.fileIds or [])) or None
    if file_ids:
        await _assert_owned_files(db, principal.user_id, dataset_ids, file_ids)
    try:
        recall_cfg, contexts = await aresolve_recall_execution(
            principal.user_id, dataset_ids
        )
    except DatasetModelBindingRequiredError as exc:
        raise BusinessError(409, str(exc), 409) from exc
    except LLMConfigResolutionError as exc:
        raise BusinessError(exc.http_status, str(exc), exc.http_status) from exc
    if body.topK is not None:
        # 覆盖在副本上，不污染数据集配置缓存对象。
        recall_cfg = recall_cfg.model_copy(update={"recall_result_limit": body.topK})
    recall_req = build_recall_request_from_config(
        query=body.query,
        user_id=principal.user_id,
        dataset_ids=dataset_ids,
        recall_cfg=recall_cfg,
        dataset_contexts=contexts,
        doc_ids=file_ids,
    )
    try:
        payload = await run_recall_json(pipeline, recall_req, principal.request_id)
    except RecallApiError as exc:
        raise BusinessError(exc.status_code, exc.message, exc.status_code) from exc
    hits = payload["hits"]
    details = {
        item["chunkId"]: item
        for item in await load_owned_chunk_details(
            db, principal.user_id, [hit["chunk_id"] for hit in hits]
        )
    }
    return success(
        {
            "hits": [
                {
                    "chunkId": hit["chunk_id"],
                    "fileId": hit["doc_id"],
                    "datasetId": hit["dataset_id"],
                    "score": hit["fused_score"],
                    "fileName": details[hit["chunk_id"]]["fileName"],
                    "content": details[hit["chunk_id"]]["content"],
                }
                for hit in hits
                if hit["chunk_id"] in details
            ],
            "failedSources": payload.get("failed_sources", []),
        }
    )
