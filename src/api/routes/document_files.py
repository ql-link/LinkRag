"""Read-side B5 file routes; parse execution remains in the existing pipeline."""

from typing import Annotated

from fastapi import Depends, Query, Request
from starlette.datastructures import UploadFile as StarletteUploadFile

from src.api.management_auth import CurrentUser, require_login
from src.api.management_http import BusinessError, ManagementRouter, success
from src.application import document_files
from src.application.document_deletion import delete_file
from src.application.document_runtime_config import capabilities
from src.application.document_uploads import DocumentUploadExecutor, upload
from src.application.parse_task_control import submit_parse
from src.config import settings

router = ManagementRouter(prefix="/api/v1", tags=["document-files"])


@router.post(
    "/datasets/{dataset_id}/files",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "parseImmediately": {"type": "boolean", "default": False},
                            "matchMode": {
                                "type": "string",
                                "enum": ["FULL_PATH", "SHALLOW_BASENAME"],
                            },
                            "documentPath": {"type": "string"},
                            "assets": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                            },
                            "assetRelativePaths": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "assetInventoryPaths": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                    }
                }
            },
        }
    },
)
async def upload_file(
    dataset_id: int,
    request: Request,
    user: Annotated[CurrentUser, Depends(require_login)],
):
    if not settings.B5_FILE_WRITES_ENABLED:
        raise BusinessError(503, "文件上传尚未切流", 503)
    # Starlette's default 1000-field cap is below Java's 5000 inventory paths.
    form = await request.form(max_fields=5500)
    file = form.get("file")
    if not isinstance(file, StarletteUploadFile):
        raise BusinessError(400, "请选择要上传的文件", 400)
    parse_raw = str(form.get("parseImmediately", "false")).strip().lower()
    if parse_raw not in {"true", "false"}:
        raise BusinessError(400, "parseImmediately 参数不合法", 400)
    parse_immediately = parse_raw == "true"
    match_mode = form.get("matchMode")
    document_path = form.get("documentPath")
    if any(
        value is not None and not isinstance(value, str) for value in (match_mode, document_path)
    ):
        raise BusinessError(400, "资源包参数不合法", 400)
    assert match_mode is None or isinstance(match_mode, str)
    assert document_path is None or isinstance(document_path, str)
    assets: list[StarletteUploadFile] = []
    for asset in form.getlist("assets"):
        if not isinstance(asset, StarletteUploadFile):
            raise BusinessError(400, "配套图片格式不合法", 400)
        assets.append(asset)
    relative_paths: list[str] = []
    for path in form.getlist("assetRelativePaths"):
        if not isinstance(path, str):
            raise BusinessError(400, "资源路径格式不合法", 400)
        relative_paths.append(path)
    inventory_paths: list[str] = []
    for path in form.getlist("assetInventoryPaths"):
        if not isinstance(path, str):
            raise BusinessError(400, "资源路径格式不合法", 400)
        inventory_paths.append(path)
    executor: DocumentUploadExecutor | None = getattr(
        request.app.state, "document_upload_executor", None
    )
    if executor is None:
        raise BusinessError(503, "文件上传队列尚未就绪", 503)
    return success(
        await upload(
            user.user_id,
            dataset_id,
            file,
            parse_immediately=parse_immediately,
            executor=executor,
            match_mode=match_mode,
            document_path=document_path,
            assets=assets,
            asset_relative_paths=relative_paths,
            asset_inventory_paths=inventory_paths,
        )
    )


@router.get("/document-file-capabilities")
async def file_capabilities(
    user: Annotated[CurrentUser, Depends(require_login)],
):
    return success(await capabilities())


@router.get("/datasets/{dataset_id}/files")
async def list_files(
    dataset_id: int,
    user: Annotated[CurrentUser, Depends(require_login)],
    uploadStatus: str | None = None,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
):
    return success(
        await document_files.list_files(user.user_id, dataset_id, page, pageSize, uploadStatus)
    )


@router.get("/files/recent")
async def recent(
    user: Annotated[CurrentUser, Depends(require_login)],
    page: int = Query(1, ge=1),
    pageSize: int = Query(5, ge=1, le=100),
):
    return success(await document_files.list_files(user.user_id, None, page, pageSize))


@router.get("/files/{file_id}")
async def detail(
    file_id: int,
    user: Annotated[CurrentUser, Depends(require_login)],
):
    return success(await document_files.detail(user.user_id, file_id))


@router.get("/datasets/{dataset_id}/files/parse-results")
async def parse_results(
    dataset_id: int,
    user: Annotated[CurrentUser, Depends(require_login)],
    fileIds: str,
):
    try:
        ids = [int(part.strip()) for part in fileIds.split(",") if part.strip()]
    except ValueError as exc:
        raise BusinessError(400, "文件 ID 不合法", 400) from exc
    return success(await document_files.parse_results(user.user_id, dataset_id, ids))


@router.post("/files/{file_id}/parse")
async def parse_file(
    file_id: int,
    user: Annotated[CurrentUser, Depends(require_login)],
    ignoreMissingAssets: bool = False,
):
    if not settings.B5_FILE_WRITES_ENABLED:
        raise BusinessError(503, "文件解析提交尚未切流", 503)
    return success(
        await submit_parse(user.user_id, file_id, ignore_missing_assets=ignoreMissingAssets)
    )


@router.delete("/files/{file_id}")
async def delete(
    file_id: int,
    user: Annotated[CurrentUser, Depends(require_login)],
):
    if not settings.B5_DELETE_WRITES_ENABLED:
        raise BusinessError(503, "文件删除尚未切流", 503)
    await delete_file(user.user_id, file_id)
    return success()
