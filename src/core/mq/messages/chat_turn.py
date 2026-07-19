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
    request_id: str = Field(..., title="请求追踪ID（仅追踪，不再充当幂等键）")
    turn_id: str = Field(..., title="轮次幂等键：前端每轮稳定 UUID，Java 据此 upsert 同一行")
    user_id: int = Field(..., title="用户ID")
    query: str = Field(..., title="用户提问")
    answer: str = Field("", title="LLM回答（GENERATING/FAILED 可空或半截）")
    config_id: int = Field(..., gt=0, title="本轮请求的全局 LLM 配置ID")
    # provider_type 放宽默认空：GENERATING 起点与前置失败（模型未解析）时无厂商信息，
    # 由终态消息补齐（chat-stream-resilient-persist）。
    provider_type: str = Field("", title="LLM厂商类型")
    model_name: str = Field("", title="模型名快照")
    references: List[str] = Field(default_factory=list, title="召回片段 chunk_id 列表（不含正文）")
    latency_ms: Optional[int] = Field(None, title="生成延迟(毫秒)")
    status: str = Field(
        ..., title="轮次状态：GENERATING（起点）/COMPLETED（成功或空命中）/FAILED（任意失败）"
    )
    error_code: Optional[str] = Field(
        None, title="失败码：RECALL_*/GENERATION_TIMEOUT（仅 FAILED）"
    )
    error_message: Optional[str] = Field(None, title="失败原因，不含堆栈（仅 FAILED）")
    # 会话标题：仅会话首轮携带（Python 基于 query 生成，LLM 不可用时回落首问截断）。
    # Java 仅在当前标题为空或仍为默认「新对话」时写入并按列宽截断，不覆盖用户手改标题；
    # 非首轮、GENERATING 起点一律为 None。
    title: Optional[str] = Field(None, title="首轮会话标题（Python 生成，供 Java 条件落库）")

    # token 已从对话消息剥离（LINK-191）：generate 用量改走统一 TokenUsageMessage。

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

    def get_log_fields(self) -> dict[str, object]:
        """返回对话消息摘要，不记录 query、answer、title 和错误正文。"""
        return {
            "message_id": self._payload.message_id,
            "conversation_id": self._payload.conversation_id,
            "request_id": self._payload.request_id,
            "turn_id": self._payload.turn_id,
            "user_id": self._payload.user_id,
            "config_id": self._payload.config_id,
            "provider_type": self._payload.provider_type,
            "model_name": self._payload.model_name,
            "status": self._payload.status,
            "reference_count": len(self._payload.references),
            "latency_ms": self._payload.latency_ms,
            "error_code": self._payload.error_code,
        }

    @classmethod
    def build(
        cls,
        *,
        conversation_id: int,
        request_id: str,
        turn_id: str,
        user_id: int,
        query: str,
        answer: str,
        config_id: int,
        status: str,
        provider_type: str = "",
        model_name: str = "",
        references: Optional[List[str]] = None,
        latency_ms: Optional[int] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        title: Optional[str] = None,
    ) -> "ChatTurnMessage":
        return cls(
            payload=ChatTurnPayload(
                conversation_id=conversation_id,
                request_id=request_id,
                turn_id=turn_id,
                user_id=user_id,
                query=query,
                answer=answer,
                config_id=config_id,
                provider_type=provider_type,
                model_name=model_name,
                status=status,
                references=references or [],
                latency_ms=latency_ms,
                error_code=error_code,
                error_message=error_message,
                title=title,
            )
        )

    @classmethod
    def parse_msg(cls, raw: str) -> ChatTurnPayload:
        envelope = cls.deserialize_envelope(raw)
        return ChatTurnPayload(**envelope["payload"])

    class MQReceiver(Protocol):
        async def on_chat_turn(self, payload: "ChatTurnPayload") -> None: ...
