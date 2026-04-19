"""
业务消息模型定义

对应 SKILL.md Extension Workflow 步骤 1-5：
每个业务场景定义一个消息类，继承 AbstractMessage，
内含 MQ_NAME 常量、MsgPayload 数据类、MQReceiver 回调接口。
"""
from abc import ABC, abstractmethod
from typing import Optional, Protocol

from pydantic import Field

from src.core.mq.message import AbstractMessage, MessagePayload


# ============================================================
# 1. 文档解析任务消息
# ============================================================

class ParseTaskPayload(MessagePayload):
    """文档解析任务载荷

    只携带 ID 和路由上下文，消费者根据 task_id 查库获取最新状态。
    """
    task_id: str = Field(..., title="任务ID", description="文档解析任务的唯一标识")
    original_file_id: int = Field(..., title="原始文件ID", description="原始文件表主键")
    file_type: str = Field(..., title="文件类型", description="文件格式（pdf/docx/html/...）")
    source_bucket: str = Field(..., title="原始文件Bucket", description="源文件对象存储 bucket")
    source_object_key: str = Field(..., title="原始文件对象Key", description="源文件对象存储 key")
    source_filename: str = Field(..., title="原始文件名", description="用户上传时的原始文件名")
    md_bucket: str = Field(..., title="Markdown Bucket", description="Markdown 输出 bucket")
    md_object_key: str = Field(..., title="Markdown 对象Key", description="Markdown 输出对象 key")
    parser_backend: Optional[str] = Field("naive", title="PDF 解析器", description="可选 PDF 解析器: naive/docling")
    docling_force_ocr: Optional[bool] = Field(False, title="Docling 强制全页 OCR", description="仅 Docling 后端生效")
    image_bucket: Optional[str] = Field(None, title="图片 Bucket", description="PDF 图片输出 bucket")
    image_prefix: Optional[str] = Field(None, title="图片前缀", description="PDF 图片输出对象 key 前缀")

    model_config = {"title": "文档解析任务载荷"}


class ParseTaskMessage(AbstractMessage):
    """文档解析 MQ 消息"""

    MQ_NAME = "tolink.rag.parse_task"
    MQ_TYPE = "PARSE_TASK"

    def __init__(self, payload: ParseTaskPayload):
        self._payload = payload

    @classmethod
    def get_mq_name(cls) -> str:
        return cls.MQ_NAME

    @classmethod
    def get_mq_type(cls) -> str:
        return cls.MQ_TYPE

    def get_payload(self) -> ParseTaskPayload:
        return self._payload

    def get_routing_key(self) -> Optional[str]:
        return self._payload.file_type

    @classmethod
    def build(
        cls,
        task_id: str,
        original_file_id: int,
        file_type: str,
        source_bucket: str,
        source_object_key: str,
        source_filename: str,
        md_bucket: str,
        md_object_key: str,
        parser_backend: Optional[str] = "naive",
        docling_force_ocr: Optional[bool] = False,
        image_bucket: Optional[str] = None,
        image_prefix: Optional[str] = None,
    ) -> "ParseTaskMessage":
        """工厂方法：构建解析任务消息"""
        return cls(
            payload=ParseTaskPayload(
                task_id=task_id,
                original_file_id=original_file_id,
                file_type=file_type,
                source_bucket=source_bucket,
                source_object_key=source_object_key,
                source_filename=source_filename,
                md_bucket=md_bucket,
                md_object_key=md_object_key,
                parser_backend=parser_backend,
                docling_force_ocr=docling_force_ocr,
                image_bucket=image_bucket,
                image_prefix=image_prefix,
            )
        )

    @classmethod
    def parse_msg(cls, raw: str) -> ParseTaskPayload:
        """反序列化为载荷对象"""
        envelope = cls.deserialize_envelope(raw)
        return ParseTaskPayload(**envelope["payload"])

    class MQReceiver(Protocol):
        """业务回调接口（消费端实现）"""
        async def on_parse_task(self, payload: "ParseTaskPayload") -> None: ...


# ============================================================
# 2. 缓存同步通知消息
# ============================================================

class CacheSyncPayload(MessagePayload):
    """缓存同步载荷"""
    user_id: str = Field(..., title="用户ID", description="需要同步缓存的用户标识")
    config_id: Optional[str] = Field(None, title="配置ID", description="具体的配置标识")
    action: str = Field(
        "refresh", title="操作类型",
        description="缓存操作类型: refresh / invalidate / warmup",
    )

    model_config = {"title": "缓存同步载荷"}


class CacheSyncMessage(AbstractMessage):
    """缓存同步 MQ 消息"""

    MQ_NAME = "tolink.rag.cache_sync"
    MQ_TYPE = "CACHE_SYNC"

    def __init__(self, payload: CacheSyncPayload):
        self._payload = payload

    @classmethod
    def get_mq_name(cls) -> str:
        return cls.MQ_NAME

    @classmethod
    def get_mq_type(cls) -> str:
        return cls.MQ_TYPE

    def get_payload(self) -> CacheSyncPayload:
        return self._payload

    @classmethod
    def build(
        cls,
        user_id: str,
        action: str = "refresh",
        config_id: Optional[str] = None,
    ) -> "CacheSyncMessage":
        return cls(
            payload=CacheSyncPayload(
                user_id=user_id,
                action=action,
                config_id=config_id,
            )
        )

    @classmethod
    def parse_msg(cls, raw: str) -> CacheSyncPayload:
        envelope = cls.deserialize_envelope(raw)
        return CacheSyncPayload(**envelope["payload"])

    class MQReceiver(Protocol):
        async def on_cache_sync(self, payload: "CacheSyncPayload") -> None: ...


# ============================================================
# 3. 用量统计上报消息
# ============================================================

class UsageReportPayload(MessagePayload):
    """用量上报载荷"""
    user_id: str = Field(..., title="用户ID")
    provider_type: str = Field(..., title="LLM厂商类型")
    model_name: str = Field(..., title="模型名称")
    prompt_tokens: int = Field(0, title="输入Token数", ge=0)
    completion_tokens: int = Field(0, title="输出Token数", ge=0)
    total_tokens: int = Field(0, title="总Token数", ge=0)

    model_config = {"title": "用量上报载荷"}


class UsageReportMessage(AbstractMessage):
    """LLM 用量上报 MQ 消息"""

    MQ_NAME = "tolink.rag.usage_report"
    MQ_TYPE = "USAGE_REPORT"

    def __init__(self, payload: UsageReportPayload):
        self._payload = payload

    @classmethod
    def get_mq_name(cls) -> str:
        return cls.MQ_NAME

    @classmethod
    def get_mq_type(cls) -> str:
        return cls.MQ_TYPE

    def get_payload(self) -> UsageReportPayload:
        return self._payload

    def get_routing_key(self) -> Optional[str]:
        return self._payload.user_id

    @classmethod
    def build(
        cls,
        user_id: str,
        provider_type: str,
        model_name: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
    ) -> "UsageReportMessage":
        return cls(
            payload=UsageReportPayload(
                user_id=user_id,
                provider_type=provider_type,
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
        )

    @classmethod
    def parse_msg(cls, raw: str) -> UsageReportPayload:
        envelope = cls.deserialize_envelope(raw)
        return UsageReportPayload(**envelope["payload"])

    class MQReceiver(Protocol):
        async def on_usage_report(self, payload: "UsageReportPayload") -> None: ...
