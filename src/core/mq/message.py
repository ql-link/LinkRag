"""
MQ 消息模型抽象

对应 SKILL.md 中的 AbstractMQ 与 MsgPayload 模式。
所有业务消息继承 AbstractMessage，只携带 ID + 路由上下文，不携带重业务对象。
"""
import json
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from src.core.mq.exceptions import MQSerializationError


class MessagePayload(BaseModel):
    """消息载荷基类

    遵循 SKILL.md 设计规则：
    - Payload 只携带 ID 和路由上下文
    - 消费者根据 ID 重新加载最新业务状态，避免 schema drift
    """
    message_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        title="消息唯一标识",
        description="用于幂等校验与消息追踪",
    )
    timestamp: float = Field(
        default_factory=time.time,
        title="消息生产时间戳",
        description="Unix epoch 秒级时间戳",
    )

    model_config = {"title": "MQ消息载荷基类"}


class AbstractMessage(ABC):
    """MQ 消息模型抽象基类

    对应 SKILL.md 中的 AbstractMQ：
    - MQ_NAME: queue/topic 名称常量
    - build(): 构建消息实例
    - parse_msg(): 反序列化
    - get_mq_name() / get_message(): 获取元信息
    """

    @classmethod
    @abstractmethod
    def get_mq_name(cls) -> str:
        """返回 queue/topic 名称常量（等价于 Java 中的 MQ_NAME）"""
        pass

    @classmethod
    @abstractmethod
    def get_mq_type(cls) -> str:
        """返回消息类型标识（用于消费者路由分发）"""
        pass

    @abstractmethod
    def get_payload(self) -> MessagePayload:
        """获取消息载荷"""
        pass

    def serialize(self) -> str:
        """序列化为 JSON 字符串（发送给 Broker）

        Returns:
            JSON 字符串，包含 mq_type 和 payload

        Raises:
            MQSerializationError: 序列化失败
        """
        try:
            envelope: Dict[str, Any] = {
                "mq_type": self.get_mq_type(),
                "mq_name": self.get_mq_name(),
                "payload": self.get_payload().model_dump(),
            }
            return json.dumps(envelope, ensure_ascii=False)
        except Exception as e:
            raise MQSerializationError(
                f"消息序列化失败: {e}"
            ) from e

    @classmethod
    def deserialize_envelope(cls, raw: str) -> Dict[str, Any]:
        """反序列化消息信封（框架层调用）

        Args:
            raw: Broker 原始消息字符串

        Returns:
            包含 mq_type, mq_name, payload 的字典

        Raises:
            MQSerializationError: 反序列化失败
        """
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or "mq_type" not in data:
                raise ValueError("消息缺少 mq_type 字段")
            return data
        except json.JSONDecodeError as e:
            raise MQSerializationError(
                f"消息 JSON 反序列化失败: {e}"
            ) from e
        except ValueError as e:
            raise MQSerializationError(str(e)) from e

    def get_routing_key(self) -> Optional[str]:
        """获取路由键（子类可覆盖以实现定向路由）"""
        return None
