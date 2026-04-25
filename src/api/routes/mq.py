"""
MQ 消息中台 API 路由

提供 MQ 消息发送、厂商信息查询等 HTTP 接口。
用于 Java 管理端通过 HTTP 触发 Python 侧的 MQ 消息投递。
"""
from fastapi import APIRouter, HTTPException
from loguru import logger

from src.services.mq_service import MQService
from src.core.mq.factory import MQFactory
from src.core.mq.messages import (
    ParseTaskMessage,
    CacheSyncMessage,
    UsageReportMessage,
)
from src.api.schemas.mq import (
    SendParseTaskRequest,
    SendCacheSyncRequest,
    SendUsageReportRequest,
    SendRawMessageRequest,
    MQResponse,
    MQVendorInfoResponse,
)

router = APIRouter(
    prefix="/api/v1/mq",
    tags=["MQ消息中台"],
)


# ==========================================
# 路由端点
# ==========================================

@router.post(
    "/send/parse-task",
    response_model=MQResponse,
    summary="发送文档解析任务消息",
    description="通过 MQ 投递文档解析任务，由消费端异步执行解析流程。",
)
async def send_parse_task(request: SendParseTaskRequest):
    """发送文档解析任务到 MQ"""
    try:
        mq_service = MQService()
        msg = ParseTaskMessage.build(
            task_id=request.task_id,
            original_file_id=request.original_file_id,
            file_type=request.file_type,
            source_bucket=request.source_bucket,
            source_object_key=request.source_object_key,
            source_filename=request.source_filename,
            md_bucket=request.md_bucket,
            md_object_key=request.md_object_key,
            pdf_parser_backend=request.pdf_parser_backend,
            docling_force_ocr=request.docling_force_ocr,
            image_bucket=request.image_bucket or request.md_bucket,
            image_prefix=request.image_prefix or request.md_object_key,
        )
        await mq_service.send(msg)
        return MQResponse(success=True, message="解析任务已投递")
    except Exception as e:
        logger.error(f"发送解析任务消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/send/cache-sync",
    response_model=MQResponse,
    summary="发送缓存同步通知消息",
    description="通知 RAG 服务刷新/失效指定用户的 LLM 配置缓存。通常由 Java 管理端在修改用户配置后触发。",
)
async def send_cache_sync(request: SendCacheSyncRequest):
    """发送缓存同步通知到 MQ"""
    try:
        mq_service = MQService()
        msg = CacheSyncMessage.build(
            user_id=request.user_id,
            action=request.action,
            config_id=request.config_id,
        )
        await mq_service.send(msg)
        return MQResponse(success=True, message="缓存同步通知已投递")
    except Exception as e:
        logger.error(f"发送缓存同步消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/send/usage-report",
    response_model=MQResponse,
    summary="发送 LLM 用量上报消息",
    description="异步上报 LLM 调用的 Token 消耗量，由消费端落库汇总。",
)
async def send_usage_report(request: SendUsageReportRequest):
    """发送用量上报消息到 MQ"""
    try:
        mq_service = MQService()
        msg = UsageReportMessage.build(
            user_id=request.user_id,
            provider_type=request.provider_type,
            model_name=request.model_name,
            prompt_tokens=request.prompt_tokens,
            completion_tokens=request.completion_tokens,
            total_tokens=request.total_tokens,
        )
        await mq_service.send(msg)
        return MQResponse(success=True, message="用量上报已投递")
    except Exception as e:
        logger.error(f"发送用量上报消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/send/raw",
    response_model=MQResponse,
    summary="发送原始消息",
    description="直接向指定 Topic/Queue 发送原始 JSON 消息，适用于对接外部系统。",
)
async def send_raw_message(request: SendRawMessageRequest):
    """发送原始消息到 MQ"""
    try:
        mq_service = MQService()
        await mq_service.send_raw(
            topic=request.topic,
            message=request.message,
            key=request.key,
        )
        return MQResponse(success=True, message="原始消息已投递")
    except Exception as e:
        logger.error(f"发送原始消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/vendor/info",
    response_model=MQVendorInfoResponse,
    summary="查询 MQ 厂商信息",
    description="返回当前激活的 MQ 厂商和所有已注册的可用厂商列表。",
)
async def get_vendor_info():
    """获取 MQ 厂商信息"""
    from src.config import settings

    factory = MQFactory()
    return MQVendorInfoResponse(
        current_vendor=settings.MQ_VENDOR,
        available_vendors=factory.list_vendors(),
    )
