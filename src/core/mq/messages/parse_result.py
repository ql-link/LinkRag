import json
from typing import Optional, Protocol

from pydantic import Field

from src.core.mq.exceptions import MQSerializationError
from src.core.mq.message import AbstractMessage, MessagePayload


class ParseResultPayload(MessagePayload):
    """文档解析终态通知载荷。"""

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
    """文档解析结果 MQ 消息。"""

    MQ_NAME = "tolink.rag.parse_result"
    MQ_TYPE = "PARSE_RESULT"

    def __init__(self, payload: ParseResultPayload):
        self._payload = payload

    @classmethod
    def get_mq_name(cls) -> str:
        return cls.MQ_NAME

    @classmethod
    def get_mq_type(cls) -> str:
        return cls.MQ_TYPE

    def get_payload(self) -> ParseResultPayload:
        return self._payload

    def get_routing_key(self) -> Optional[str]:
        return self._payload.task_id

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
        async def on_parse_result(self, payload: "ParseResultPayload") -> None: ...
