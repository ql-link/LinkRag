"""对话轮次完成 MQ 消息（chat-message-persistence）。

RAG 问答在 Python 端流式生成结束后，把一轮问答的**对话内容**（query / answer / 召回引用 /
状态）汇成一条消息发往 Java；Java 消费后落库 chat_message 行并更新 chat_conversation。
Python 不直接写这两张表的行数据。

职责拆分（LINK-191）：本消息**只负责对话内容持久化**，不再携带 token。对话 generate 的
token 用量随统一的 ``TokenUsageMessage`` 单独上报（stage='chat'、operation='generate'），
与对话内容解耦——避免 token 统计链路依赖携带大文本（query/answer）的消息。
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
    model_name: str = Field("", title="模型名快照")
    references: List[str] = Field(default_factory=list, title="召回片段 chunk_id 列表（不含正文）")
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
        model_name: str,
        status: str,
        references: Optional[List[str]] = None,
    ) -> "ChatTurnMessage":
        return cls(
            payload=ChatTurnPayload(
                conversation_id=conversation_id,
                request_id=request_id,
                user_id=user_id,
                query=query,
                answer=answer,
                config_id=config_id,
                model_name=model_name,
                status=status,
                references=references or [],
            )
        )

    @classmethod
    def parse_msg(cls, raw: str) -> ChatTurnPayload:
        envelope = cls.deserialize_envelope(raw)
        return ChatTurnPayload(**envelope["payload"])

    class MQReceiver(Protocol):
        async def on_chat_turn(self, payload: "ChatTurnPayload") -> None: ...
