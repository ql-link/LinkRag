"""对话轮次完成 MQ 消息（chat-message-persistence）。

RAG 问答在 Python 端流式生成结束后，把一轮问答的完整数据（query / answer / 用量 /
召回引用 / 状态）汇成一条消息发往 Java；Java 消费后在单事务里落库 chat_message 行、
llm_usage_log 行并更新 chat_conversation。Python 不直接写这三张表的行数据。

与 ``usage_report`` 区分：``usage_report`` 只承载 token 数、语义是纯用量，保留给非对话型
LLM 调用；对话轮次落库走本消息。
"""

from typing import List, Optional, Protocol

from pydantic import Field

from src.core.mq.message import AbstractMessage, MessagePayload


class ChatTurnPayload(MessagePayload):
    """对话轮次完成载荷。"""

    conversation_id: int = Field(..., title="所属对话ID")
    request_id: str = Field(..., title="请求追踪ID/幂等键")
    user_id: int = Field(..., title="用户ID")
    query: str = Field(..., title="用户提问")
    answer: str = Field("", title="LLM回答（partial 为半截，failed 可空）")
    config_id: int = Field(..., title="本轮所用 LLM 配置ID")
    provider_type: str = Field(..., title="LLM厂商类型")
    model_name: str = Field("", title="模型名快照")
    prompt_tokens: int = Field(0, title="输入Token数", ge=0)
    completion_tokens: int = Field(0, title="输出Token数", ge=0)
    total_tokens: int = Field(0, title="总Token数", ge=0)
    references: List[str] = Field(default_factory=list, title="召回片段 chunk_id 列表（不含正文）")
    latency_ms: Optional[int] = Field(None, title="生成延迟(毫秒)")
    status: str = Field(..., title="轮次状态：success/partial/failed")

    model_config = {"title": "对话轮次完成载荷"}


class ChatTurnMessage(AbstractMessage):
    """对话轮次完成 MQ 消息（Python -> Java，供 Java 落库）。"""

    MQ_NAME = "tolink.rag.chat_turn"
    MQ_TYPE = "CHAT_TURN"

    def __init__(self, payload: ChatTurnPayload):
        self._payload = payload

    @classmethod
    def get_mq_name(cls) -> str:
        return cls.MQ_NAME

    @classmethod
    def get_mq_type(cls) -> str:
        return cls.MQ_TYPE

    def get_payload(self) -> ChatTurnPayload:
        return self._payload

    def get_routing_key(self) -> Optional[str]:
        # 以 conversation_id 为分区键，保证同一对话的轮次有序投递。
        return str(self._payload.conversation_id)

    @classmethod
    def build(
        cls,
        *,
        conversation_id: int,
        request_id: str,
        user_id: int,
        query: str,
        answer: str,
        config_id: int,
        provider_type: str,
        model_name: str,
        status: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        references: Optional[List[str]] = None,
        latency_ms: Optional[int] = None,
    ) -> "ChatTurnMessage":
        return cls(
            payload=ChatTurnPayload(
                conversation_id=conversation_id,
                request_id=request_id,
                user_id=user_id,
                query=query,
                answer=answer,
                config_id=config_id,
                provider_type=provider_type,
                model_name=model_name,
                status=status,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                references=references or [],
                latency_ms=latency_ms,
            )
        )

    @classmethod
    def parse_msg(cls, raw: str) -> ChatTurnPayload:
        envelope = cls.deserialize_envelope(raw)
        return ChatTurnPayload(**envelope["payload"])

    class MQReceiver(Protocol):
        async def on_chat_turn(self, payload: "ChatTurnPayload") -> None: ...
