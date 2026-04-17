"""
文档解析 API 路由

提供同步解析和异步任务提交两个端点。
异步任务通过 MQ 中台投递，由消费端异步处理。
"""
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel, Field

from src.services.parse_task_service import ParseTaskService
from src.services.mq_service import MQService
from src.core.mq.messages import ParseTaskMessage

router = APIRouter(
    prefix="/api/v1/parser",
    tags=["文档解析"],
)


class TaskSubmitRequest(BaseModel):
    """异步解析任务提交请求"""
    task_id: str = Field(..., title="任务ID", description="文档解析任务唯一标识")
    document_id: str = Field(..., title="文档ID", description="待解析文档标识")
    file_url: str = Field(..., title="文件URL", description="OSS 文件下载地址")
    file_type: str = Field(..., title="文件类型", description="文件格式 (pdf/docx/html/txt)")

    model_config = {"title": "异步解析任务请求体"}


class TaskSubmitResponse(BaseModel):
    """异步解析任务提交响应"""
    code: int = Field(200, title="状态码")
    message: str = Field("", title="描述信息")
    data: dict = Field(default_factory=dict, title="响应数据")

    model_config = {"title": "异步解析任务响应体"}


@router.post(
    "/extract_sync",
    summary="同步提取文档转 Markdown",
    description="上传文件后同步解析并返回 Markdown 内容。适用于测试或小文件直传场景。",
)
async def extract_sync(file: UploadFile = File(...), file_type: str = Form(...)):
    """同步解析文档"""
    try:
        file_stream = await file.read()
        result = ParseTaskService.process_sync(file_stream, file_type)
        return {
            "code": 200,
            "message": "success",
            "data": {
                "file_type": file_type,
                "markdown": result["markdown"],
                "metadata": result["metadata"]
            },
            "time_cost_ms": result["time_cost_ms"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
            document_id=request.document_id,
            file_url=request.file_url,
            file_type=request.file_type,
        )
        await mq_service.send(msg)
        return TaskSubmitResponse(
            code=200,
            message="Task accepted and queued via MQ",
            data={
                "task_id": request.task_id,
                "status": "pending",
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))