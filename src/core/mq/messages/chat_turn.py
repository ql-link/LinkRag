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
    request_id: str = Field(..., title="请求追踪ID（仅追踪，不再充当幂等键）")
    turn_id: str = Field(..., title="轮次幂等键：前端每轮稳定 UUID，Java 据此 upsert 同一行")
    user_id: int = Field(..., title="用户ID")
    query: str = Field(..., title="用户提问")
    answer: str = Field("", title="LLM回答（GENERATING/FAILED 可空或半截）")
    config_id: int = Field(..., title="本轮所用 LLM 配置ID")
    # provider_type 放宽默认空：GENERATING 起点与前置失败（模型未解析）时无厂商信息，
    # 由终态消息补齐（chat-stream-resilient-persist）。
    provider_type: str = Field("", title="LLM厂商类型")
    model_name: str = Field("", title="模型名快照")
    prompt_tokens: int = Field(0, title="输入Token数", ge=0)
    completion_tokens: int = Field(0, title="输出Token数", ge=0)
    total_tokens: int = Field(0, title="总Token数", ge=0)
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
        turn_id: str,
        user_id: int,
        query: str,
        answer: str,
        config_id: int,
        status: str,
        provider_type: str = "",
        model_name: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
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
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
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
