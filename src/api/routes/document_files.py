"""Read-side B5 file routes; parse execution remains in the existing pipeline."""

from typing import Annotated

from fastapi import Depends, File, Form, Query, Request, UploadFile

from src.api.management_auth import CurrentUser, require_login
from src.api.management_http import BusinessError, ManagementRouter, success
from src.application import document_files
from src.application.document_runtime_config import capabilities
from src.application.document_deletion import delete_file
from src.application.parse_task_control import submit_parse
from src.application.document_uploads import DocumentUploadExecutor, upload
from src.config import settings

router = ManagementRouter(prefix="/api/v1", tags=["document-files"])


@router.post("/datasets/{dataset_id}/files")
async def upload_file(
    dataset_id: int, request: Request,
    user: Annotated[CurrentUser, Depends(require_login)],
    file: UploadFile = File(...), parseImmediately: bool = Form(False),
    matchMode: str | None = Form(None), documentPath: str | None = Form(None),
):
    if not settings.B5_FILE_WRITES_ENABLED:
        raise BusinessError(503, "文件上传尚未切流", 503)
    form = await request.form()
    if matchMode or documentPath or any(
        key in form for key in ("assets", "assetRelativePaths", "assetInventoryPaths")
    ):
        raise BusinessError(503, "Markdown 资源包上传尚未切流", 503)
    executor: DocumentUploadExecutor | None = getattr(request.app.state, "document_upload_executor", None)
    if executor is None:
        raise BusinessError(503, "文件上传队列尚未就绪", 503)
    return success(await upload(
        user.user_id, dataset_id, file,
        parse_immediately=parseImmediately, executor=executor,
    ))


@router.get("/document-file-capabilities")
async def file_capabilities(
    user: Annotated[CurrentUser, Depends(require_login)],
):
    return success(await capabilities())


@router.get("/datasets/{dataset_id}/files")
async def list_files(
    dataset_id: int, user: Annotated[CurrentUser, Depends(require_login)],
    uploadStatus: str | None = None,
    page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100),
):
    return success(await document_files.list_files(
        user.user_id, dataset_id, page, pageSize, uploadStatus
    ))


@router.get("/files/recent")
async def recent(
    user: Annotated[CurrentUser, Depends(require_login)],
    page: int = Query(1, ge=1), pageSize: int = Query(5, ge=1, le=100),
):
    return success(await document_files.list_files(user.user_id, None, page, pageSize))


@router.get("/files/{file_id}")
async def detail(
    file_id: int, user: Annotated[CurrentUser, Depends(require_login)],
):
    return success(await document_files.detail(user.user_id, file_id))


@router.get("/datasets/{dataset_id}/files/parse-results")
async def parse_results(
    dataset_id: int, user: Annotated[CurrentUser, Depends(require_login)],
    fileIds: str,
):
    try:
        ids = [int(part.strip()) for part in fileIds.split(",") if part.strip()]
    except ValueError as exc:
        raise BusinessError(400, "文件 ID 不合法", 400) from exc
    return success(await document_files.parse_results(user.user_id, dataset_id, ids))


@router.post("/files/{file_id}/parse")
async def parse_file(
    file_id: int, user: Annotated[CurrentUser, Depends(require_login)],
    ignoreMissingAssets: bool = False,
):
    if not settings.B5_FILE_WRITES_ENABLED:
        raise BusinessError(503, "文件解析提交尚未切流", 503)
    return success(await submit_parse(
        user.user_id, file_id, ignore_missing_assets=ignoreMissingAssets
    ))


@router.delete("/files/{file_id}")
async def delete(
    file_id: int, user: Annotated[CurrentUser, Depends(require_login)],
):
    if not settings.B5_DELETE_WRITES_ENABLED:
        raise BusinessError(503, "文件删除尚未切流", 503)
    await delete_file(user.user_id, file_id)
    return success()
