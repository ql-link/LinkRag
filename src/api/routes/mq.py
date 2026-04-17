"""
MQ 消息中台 API 路由

提供 MQ 消息发送、厂商信息查询等 HTTP 接口。
用于 Java 管理端通过 HTTP 触发 Python 侧的 MQ 消息投递。
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from loguru import logger

from src.services.mq_service import MQService
from src.core.mq.factory import MQFactory
from src.core.mq.messages import (
    ParseTaskMessage,
    CacheSyncMessage,
    UsageReportMessage,
)

router = APIRouter(
    prefix="/api/v1/mq",
    tags=["MQ消息中台"],
)


# ==========================================
# 请求/响应模型
# ==========================================

class SendParseTaskRequest(BaseModel):
    """文档解析任务消息发送请求"""
    task_id: str = Field(..., title="任务ID", description="文档解析任务唯一标识")
    document_id: str = Field(..., title="文档ID", description="待解析文档标识")
    file_url: str = Field(..., title="文件URL", description="OSS 文件下载地址")
    file_type: str = Field(..., title="文件类型", description="文件格式 (pdf/docx/html/...)")

    model_config = {"title": "发送解析任务请求体"}


class SendCacheSyncRequest(BaseModel):
    """缓存同步消息发送请求"""
    user_id: str = Field(..., title="用户ID", description="需要同步缓存的用户标识")
    action: str = Field("refresh", title="操作类型", description="refresh / invalidate / warmup")
    config_id: Optional[str] = Field(None, title="配置ID", description="具体配置标识")

    model_config = {"title": "发送缓存同步请求体"}


class SendUsageReportRequest(BaseModel):
    """用量上报消息发送请求"""
    user_id: str = Field(..., title="用户ID")
    provider_type: str = Field(..., title="LLM厂商类型")
    model_name: str = Field(..., title="模型名称")
    prompt_tokens: int = Field(0, ge=0, title="输入Token数")
    completion_tokens: int = Field(0, ge=0, title="输出Token数")
    total_tokens: int = Field(0, ge=0, title="总Token数")

    model_config = {"title": "发送用量上报请求体"}


class SendRawMessageRequest(BaseModel):
    """原始消息发送请求"""
    topic: str = Field(..., title="目标Topic/Queue", description="消息投递目标")
    message: str = Field(..., title="消息体", description="JSON 字符串格式的消息内容")
    key: Optional[str] = Field(None, title="路由键", description="Kafka partition key / RabbitMQ routing key")

    model_config = {"title": "原始消息发送请求体"}


class MQResponse(BaseModel):
    """MQ 操作响应"""
    success: bool = Field(..., title="操作结果")
    message: str = Field("", title="描述信息")

    model_config = {"title": "MQ操作响应"}


class MQVendorInfoResponse(BaseModel):
    """MQ 厂商信息响应"""
    current_vendor: str = Field(..., title="当前厂商", description="当前激活的 MQ 厂商")
    available_vendors: list[str] = Field(..., title="可用厂商列表")

    model_config = {"title": "MQ厂商信息响应"}


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
            document_id=request.document_id,
            file_url=request.file_url,
            file_type=request.file_type,
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
