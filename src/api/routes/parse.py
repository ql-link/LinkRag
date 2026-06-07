"""
文档解析 API 路由

提供同步解析和异步任务提交两个端点。
异步任务通过 MQ 中台投递，由消费端异步处理。
"""

from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from loguru import logger

from src.config import settings
from src.services.parse_task_service import ParseTaskService
from src.services.mq_service import MQService
from src.services.storage.factory import StorageFactory
from src.core.mq.messages import ParseTaskMessage
from src.core.pipeline.parse_task import temp_workspace
from src.api.schemas.parse import TaskSubmitRequest, TaskSubmitResponse

router = APIRouter(
    prefix="/api/v1/parser",
    tags=["文档解析"],
)


@router.post(
    "/extract_sync",
    summary="同步提取文档转 Markdown",
    description="上传文件后同步解析并返回 Markdown 内容。仅用于测试或联调，不作为生产上传入口。",
)
async def extract_sync(
    file: UploadFile = File(...),
    file_type: str = Form(...),
    pdf_parser_backend: str = Form("mineru", alias="parser_backend"),
    docling_force_ocr: bool = Form(False),
    image_bucket: str | None = Form(None),
    image_prefix: str | None = Form(None),
    source_file_url: str | None = Form(None),
    mineru_model_version: str = Form("vlm"),
):
    """同步解析文档"""
    # multipart upload 接到 bytes 后，统一落到 PARSE_TEMP_DIR 转成 Path 喂给协议化的
    # parser；与 MQ 主流程保持同一份临时文件生命周期约束，finally 兜底清理。
    upload_path: Path | None = None
    try:
        parser_kwargs = {}
        if file_type.lower() == "pdf":
            parser_kwargs["backend"] = pdf_parser_backend
            parser_kwargs["docling_force_ocr"] = docling_force_ocr
            parser_kwargs["source_file_url"] = source_file_url
            parser_kwargs["mineru_model_version"] = mineru_model_version
            if image_bucket and image_prefix:
                parser_kwargs["image_bucket"] = image_bucket
                parser_kwargs["image_prefix"] = image_prefix
                parser_kwargs["storage"] = StorageFactory.get_storage()

        task_id = file.filename or "extract_sync"
        upload_path = temp_workspace.create_temp_file(task_id, Path(settings.PARSE_TEMP_DIR))
        upload_path.parent.mkdir(parents=True, exist_ok=True)
        # FastAPI UploadFile 内部已经走 SpooledTemporaryFile，这里仅在边界处把句柄落地为
        # 协议要求的 Path；分块写入避免一次性 .read() 把大文件全量读进内存。
        with open(upload_path, "wb") as fp:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                fp.write(chunk)

        result = await ParseTaskService.aprocess(
            upload_path,
            file_type,
            source_file=file.filename,
            **parser_kwargs,
        )
        return {
            "code": 200,
            "message": "success",
            "data": {
                "file_type": file_type,
                "pdf_parser_backend": result["metadata"].get(
                    "pdf_parser_backend", pdf_parser_backend
                ),
                "markdown": result["markdown"],
                "metadata": result["metadata"],
                "warning": "该接口仅用于测试联调，生产流程请通过 Java 上传后发送 Kafka 解析任务",
            },
            "time_cost_ms": result["time_cost_ms"],
        }
    except Exception as e:
        logger.exception("/parser 接口处理失败")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        temp_workspace.safe_unlink(upload_path)


@router.post(
    "/task/submit",
    response_model=TaskSubmitResponse,
    summary="提交异步解析任务",
    description="通过 MQ 中台投递文档解析任务。Java 管理端主调接口，任务由后台消费者异步执行。",
)
async def submit_async_task(request: TaskSubmitRequest):
    """提交异步解析任务到 MQ"""
    try:
        mq_service = MQService()
        msg = ParseTaskMessage.build(
            task_id=request.task_id,
            original_file_id=request.original_file_id,
            document_parse_task_id=request.document_parse_task_id,
            user_id=request.user_id,
            dataset_id=request.dataset_id,
            file_type=request.file_type,
            source_bucket=request.source_bucket,
            source_object_key=request.source_object_key,
            source_filename=request.source_filename,
            md_bucket=request.md_bucket,
            md_object_key=request.md_object_key,
            trigger_mode=request.trigger_mode,
            pdf_parser_backend=request.pdf_parser_backend,
            docling_force_ocr=request.docling_force_ocr,
            image_bucket=request.image_bucket or request.md_bucket,
            image_prefix=request.image_prefix or request.md_object_key,
        )
        await mq_service.send(msg)
        return TaskSubmitResponse(
            code=200,
            message="Task accepted and queued via MQ",
            data={
                "task_id": request.task_id,
                "status": "created",
            },
        )
    except Exception as e:
        logger.exception("/parser 接口处理失败")
        raise HTTPException(status_code=500, detail=str(e))
