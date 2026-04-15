from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from src.services.parse_task_service import ParseTaskService
from src.services.mq_consumer import consume_parse_task

router = APIRouter(prefix="/api/v1/parser", tags=["解析模块"])

class TaskSubmitRequest(BaseModel):
    task_id: str
    document_id: str
    file_url: str
    file_type: str

@router.post("/extract_sync")
async def extract_sync(file: UploadFile = File(...), file_type: str = Form(...)):
    """接口 1: 同步提取文档转 Markdown (测试或小文件直传)"""
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

@router.post("/task/submit")
async def submit_async_task(request: TaskSubmitRequest):
    """接口 2: 提交异步解析任务 (Java 端主调接口)"""
    try:
        # 投递异步任务到 Redis 队列
        consume_parse_task.delay(
            task_id=request.task_id,
            document_id=request.document_id,
            file_url=request.file_url,
            file_type=request.file_type
        )
        return {
            "code": 200,
            "message": "Task accepted and queued",
            "data": {
                "task_id": request.task_id,
                "status": "pending"
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))