from typing import Optional, Protocol

from pydantic import Field

from src.core.mq.message import AbstractMessage, MessagePayload


class UsageReportPayload(MessagePayload):
    """用量上报载荷。"""

    user_id: str = Field(..., title="用户ID")
    provider_type: str = Field(..., title="LLM厂商类型")
    model_name: str = Field(..., title="模型名称")
    prompt_tokens: int = Field(0, title="输入Token数", ge=0)
    completion_tokens: int = Field(0, title="输出Token数", ge=0)
    total_tokens: int = Field(0, title="总Token数", ge=0)

    model_config = {"title": "用量上报载荷"}


class UsageReportMessage(AbstractMessage):
    """LLM 用量上报 MQ 消息。"""

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
