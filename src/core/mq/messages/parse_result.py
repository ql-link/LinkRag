import json
from typing import Optional, Protocol

from pydantic import Field

from src.core.mq.exceptions import MQSerializationError
from src.core.mq.message import AbstractMessage, MessagePayload


class ParseResultPayload(MessagePayload):
    """文档解析终态通知载荷。

    该载荷由 Python 解析服务发送给 Java 端，表示一次解析任务已经进入终态。
    发送给 Java 的通知消息只包含解析结果业务字段；异常或中断原因统一放在
    ``failure_reason``。
    """

    task_id: str = Field(..., title="解析任务ID", description="document_parsed_log.task_id")
    original_file_id: int = Field(..., title="原始文件ID", description="document_original_file.id")
    document_parse_task_id: int = Field(
        ..., title="文件解析表ID", description="document_parse_task.id"
    )
    dataset_id: int = Field(..., title="数据集ID", description="文件所属数据集ID")
    user_id: int = Field(..., title="用户ID", description="文件所属用户ID")
    task_status: str = Field(..., title="任务终态", description="success/failed")
    failure_reason: Optional[str] = Field(
        None, title="失败原因", description="解析失败时的业务化原因"
    )
    parse_finished_at: str = Field(..., title="解析完成时间", description="ISO 8601 格式时间")

    model_config = {"title": "文档解析结果通知载荷"}


class ParseResultMessage(AbstractMessage):
    """文档解析结果 MQ 消息。

    该消息发布到 ``tolink.rag.parse_result``，用于把 Python 端解析终态回传给 Java。
    """

    MQ_NAME = "tolink.rag.parse_result"
    MQ_TYPE = "PARSE_RESULT"

    def __init__(self, payload: ParseResultPayload):
        """初始化解析结果消息。

        Args:
            payload: 已通过 Pydantic 校验的解析结果载荷。
        """
        self._payload = payload

    @classmethod
    def get_mq_name(cls) -> str:
        """返回 MQ Topic/Queue 名称。"""
        return cls.MQ_NAME

    @classmethod
    def get_mq_type(cls) -> str:
        """返回业务消息类型标识。"""
        return cls.MQ_TYPE

    def get_payload(self) -> ParseResultPayload:
        """获取解析结果载荷。"""
        return self._payload

    def get_routing_key(self) -> Optional[str]:
        """返回消息路由键。

        使用 task_id 作为路由键，便于 Java 端按解析任务维度关联请求与结果。
        """
        return self._payload.task_id

    def serialize(self) -> str:
        """序列化为 Java 端约定的解析结果通知。

        ParseResultPayload 继承 MessagePayload 以复用校验体系，但发给 Java 的
        消息体只保留解析结果业务字段，不输出 mq_type/mq_name 信封、
        message_id/timestamp 或用户通知字段。
        """
        try:
            payload = self._payload.model_dump(exclude={"message_id", "timestamp"})
            return json.dumps(payload, ensure_ascii=False)
        except Exception as exc:
            raise MQSerializationError(f"消息序列化失败: {exc}") from exc

    @classmethod
    def build(
        cls,
        task_id: str,
        original_file_id: int,
        document_parse_task_id: int,
        dataset_id: int,
        user_id: int,
        task_status: str,
        parse_finished_at: str,
        failure_reason: Optional[str] = None,
    ) -> "ParseResultMessage":
        """构造解析结果消息。

        Args:
            task_id: 解析任务幂等 ID。
            original_file_id: 原始文件 ID。
            document_parse_task_id: Java 侧文件解析记录 ID。
            dataset_id: 数据集 ID。
            user_id: 用户 ID。
            task_status: 解析终态，通常为 success 或 failed。
            parse_finished_at: ISO 8601 格式的解析完成时间。
            failure_reason: 失败原因，成功时为空。

        Returns:
            可由 MQService 发送的解析结果消息对象。
        """
        return cls(
            payload=ParseResultPayload(
                task_id=task_id,
                original_file_id=original_file_id,
                document_parse_task_id=document_parse_task_id,
                dataset_id=dataset_id,
                user_id=user_id,
                task_status=task_status,
                failure_reason=failure_reason,
                parse_finished_at=parse_finished_at,
            )
        )

    @classmethod
    def parse_msg(cls, raw: str) -> ParseResultPayload:
        """反序列化解析结果消息。

        Args:
            raw: MQ 收到的原始 JSON 字符串。

        Returns:
            校验后的 ParseResultPayload。

        Raises:
            MQSerializationError: JSON 格式非法或 payload 字段校验失败。
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MQSerializationError(f"消息 JSON 反序列化失败: {exc}") from exc

        if not isinstance(data, dict):
            raise MQSerializationError("消息必须是 JSON 对象")

        payload_data = data.get("payload", data)
        try:
            return ParseResultPayload(**payload_data)
        except Exception as exc:
            raise MQSerializationError(
                f"ParseResultPayload 字段校验失败: {exc}，原始消息前200字符: {raw[:200]}"
            ) from exc

    class MQReceiver(Protocol):
        """解析结果消费者协议。

        实现该协议的接收方可被 MQ 中台适配，用于消费 parse_result 终态消息。
        """

        async def on_parse_result(self, payload: "ParseResultPayload") -> None: ...
