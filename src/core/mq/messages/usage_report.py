"""LLM 用量上报 MQ 消息（Python -> Java/统计侧，供 Java 落库 llm_usage_log）。

承载全链路非对话型模型调用的用量：解析侧 embed/vision/table、召回侧 embed/rerank。
每条消息描述「某用户、某阶段、某操作、用了哪个模型、消耗多少 token」，由 Java 消费后
直接落 llm_usage_log 行（可空字段缺失时落 NULL）。

口径：token 一律由模型返回，向量类调用 completion_tokens=0。stage/operation 标识归属，
由发起调用的业务层填——provider 层不知道自己处在哪个阶段。

与 ``chat_turn`` 区分：对话最终 generate 的用量随 ChatTurnMessage 与 chat_message 同事务
落库（Java 落库时补 stage='chat'、operation='generate'），不走本消息。
"""

from typing import Optional, Protocol

from pydantic import Field

from src.core.mq.message import AbstractMessage, MessagePayload


class UsageReportPayload(MessagePayload):
    """用量上报载荷。"""

    user_id: str = Field(..., title="用户ID")
    provider_type: str = Field(..., title="LLM厂商类型")
    model_name: str = Field(..., title="模型名称")
    prompt_tokens: int = Field(0, title="输入Token数", ge=0)
    completion_tokens: int = Field(0, title="输出Token数（向量类调用恒为0）", ge=0)
    total_tokens: int = Field(0, title="总Token数", ge=0)
    # 归属维度
    stage: str = Field(..., title="阶段：parse/recall/chat")
    operation: str = Field(..., title="操作：embed/sparse/rerank/vision/table")
    # 业务锚点 / 关联键（能拿到则带，Java 落库时缺失落 NULL）
    config_id: Optional[int] = Field(None, title="LLM 用户配置ID；系统配置调用可缺省")
    task_id: Optional[str] = Field(None, title="解析任务锚点（parse 阶段带）")
    conversation_id: Optional[int] = Field(None, title="对话ID（recall/chat 阶段带）")
    request_id: Optional[str] = Field(None, title="请求追踪ID，关联同一次召回的多条用量")
    latency_ms: Optional[int] = Field(None, title="该调用耗时(毫秒)")
    status: str = Field("success", title="调用状态：success/partial/failed")

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
        *,
        user_id: str,
        provider_type: str,
        model_name: str,
        stage: str,
        operation: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        config_id: Optional[int] = None,
        task_id: Optional[str] = None,
        conversation_id: Optional[int] = None,
        request_id: Optional[str] = None,
        latency_ms: Optional[int] = None,
        status: str = "success",
    ) -> "UsageReportMessage":
        return cls(
            payload=UsageReportPayload(
                user_id=user_id,
                provider_type=provider_type,
                model_name=model_name,
                stage=stage,
                operation=operation,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                config_id=config_id,
                task_id=task_id,
                conversation_id=conversation_id,
                request_id=request_id,
                latency_ms=latency_ms,
                status=status,
            )
        )

    @classmethod
    def parse_msg(cls, raw: str) -> UsageReportPayload:
        envelope = cls.deserialize_envelope(raw)
        return UsageReportPayload(**envelope["payload"])

    class MQReceiver(Protocol):
        async def on_usage_report(self, payload: "UsageReportPayload") -> None: ...
