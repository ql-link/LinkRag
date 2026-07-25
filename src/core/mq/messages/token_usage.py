"""统一 Token 用量上报 MQ 消息（Python -> Java/统计侧，供 Java 落库 llm_usage_log）。

承载**全部**模型调用的 token 用量：对话 chat generate、解析 embed/vision/table、召回
embed/rerank。每条消息描述「某用户、某阶段、某操作、用了哪个模型、消耗多少 token」，由
Java 消费后直接落 llm_usage_log 一行（可空字段缺失时落 NULL）。

口径：token 一律由模型返回，向量类调用 completion_tokens=0。stage/operation 标识归属，
由发起调用的业务层填——provider 层不知道自己处在哪个阶段。

与 ``chat_turn`` 区分：``chat_turn`` 只承载对话内容（query/answer/references），负责
``chat_message`` 持久化，**不再携带 token**；对话 generate 的 token 用量随本消息上报
（stage='chat'、operation='generate'）。

> 兼容性：MQ topic 与 mq_type 沿用历史值 ``tolink.rag.usage_report`` / ``USAGE_REPORT``，
> Java 现有 usage_report 消费者无需重新绑定 topic——本次变化对 Java 是纯增量（该消费者现在
> 也会收到 generate 行），仅需 chat_turn 消费者停止据其写 llm_usage_log generate 行。
"""

from typing import Optional, Protocol

from pydantic import Field

from src.core.mq.message import AbstractMessage, MessagePayload


class TokenUsagePayload(MessagePayload):
    """Token 用量上报载荷。"""

    user_id: str = Field(..., title="用户ID")
    provider_type: str = Field(..., title="LLM厂商类型")
    model_name: str = Field(..., title="模型名称")
    prompt_tokens: int = Field(0, title="输入Token数", ge=0)
    completion_tokens: int = Field(0, title="输出Token数（向量类调用恒为0）", ge=0)
    total_tokens: int = Field(0, title="总Token数", ge=0)
    # 归属维度
    stage: str = Field(..., title="阶段：parse/recall/chat")
    operation: str = Field(..., title="操作：embed/sparse/rerank/vision/table/generate")
    # 新契约中 SYSTEM/USER 调用都携带同一全局 ID。
    config_id: int = Field(..., gt=0, title="全局 LLM 配置ID")
    task_id: Optional[str] = Field(None, title="解析任务锚点（parse 阶段带）")
    latency_ms: Optional[int] = Field(None, title="该调用耗时(毫秒)")
    status: str = Field("success", title="调用状态：success/partial/failed")

    model_config = {"title": "Token用量上报载荷"}


class TokenUsageMessage(AbstractMessage):
    """统一 Token 用量上报 MQ 消息。"""

    # topic / type 沿用历史值，避免 Java 重新绑定 queue（详见模块 docstring）。
    MQ_NAME = "tolink.rag.usage_report"
    MQ_TYPE = "USAGE_REPORT"

    def __init__(self, payload: TokenUsagePayload):
        self._payload = payload

    @classmethod
    def get_mq_name(cls) -> str:
        return cls.MQ_NAME

    @classmethod
    def get_mq_type(cls) -> str:
        return cls.MQ_TYPE

    def get_payload(self) -> TokenUsagePayload:
        return self._payload

    def get_routing_key(self) -> Optional[str]:
        return self._payload.user_id

    def get_log_fields(self) -> dict[str, object]:
        """返回用量消息摘要，不包含任何模型请求或响应正文。"""
        return {
            "message_id": self._payload.message_id,
            "user_id": self._payload.user_id,
            "provider_type": self._payload.provider_type,
            "model_name": self._payload.model_name,
            "stage": self._payload.stage,
            "operation": self._payload.operation,
            "prompt_tokens": self._payload.prompt_tokens,
            "completion_tokens": self._payload.completion_tokens,
            "total_tokens": self._payload.total_tokens,
            "config_id": self._payload.config_id,
            "task_id": self._payload.task_id,
            "latency_ms": self._payload.latency_ms,
            "status": self._payload.status,
        }

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
        config_id: int,
        task_id: Optional[str] = None,
        latency_ms: Optional[int] = None,
        status: str = "success",
    ) -> "TokenUsageMessage":
        return cls(
            payload=TokenUsagePayload(
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
                latency_ms=latency_ms,
                status=status,
            )
        )

    @classmethod
    def parse_msg(cls, raw: str) -> TokenUsagePayload:
        envelope = cls.deserialize_envelope(raw)
        return TokenUsagePayload(**envelope["payload"])

    class MQReceiver(Protocol):
        async def on_token_usage(self, payload: "TokenUsagePayload") -> None: ...
