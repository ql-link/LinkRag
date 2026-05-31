"""
MQ 能力接口契约 (Capability Interfaces)

定义 MQ Vendor Adapter 必须实现的接口，业务代码只依赖这些抽象。
对应 SKILL.md 中的 MQSend / MQMsgReceiver 接口层。
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Callable, Awaitable, Dict, List, Optional


class MQVendorType(str, Enum):
    """MQ 厂商类型枚举"""
    KAFKA = "kafka"
    RABBITMQ = "rabbitmq"


class IMQSender(ABC):
    """消息发送接口

    对应 SKILL.md 中的 MQSend 抽象。
    业务代码通过此接口发送消息，不直接依赖 KafkaProducer / RabbitMQ Channel。
    """

    @abstractmethod
    async def send(
        self,
        topic: str,
        message: str,
        *,
        key: str | None = None,
        headers: Dict[str, str] | None = None,
        delay_ms: int | None = None,
    ) -> None:
        """发送消息

        Args:
            topic: 目标 Topic / Queue 名称
            message: JSON 序列化后的消息体
            key: 消息路由键（Kafka partition key / RabbitMQ routing key）
            headers: 消息头元数据
            delay_ms: 延迟投递毫秒数（RabbitMQ 支持，Kafka 需业务层实现）
        """
        pass

    @abstractmethod
    async def send_batch(
        self,
        topic: str,
        messages: List[str],
        *,
        keys: List[str | None] | None = None,
    ) -> None:
        """批量发送消息

        Args:
            topic: 目标 Topic / Queue
            messages: JSON 序列化后的消息体列表
            keys: 每条消息的路由键列表（长度须与 messages 一致）
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """释放生产者资源"""
        pass


class IMQReceiver(ABC):
    """消息接收接口

    对应 SKILL.md 中的 MQMsgReceiver 框架层。
    框架层从 Broker 拉取/推送消息，反序列化后分发给 BusinessReceiver 回调。
    """

    @abstractmethod
    async def subscribe(
        self,
        topic: str,
        group_id: str,
        callback: Callable[[str, Dict[str, Any]], Awaitable[None]],
        *,
        from_beginning: bool = False,
    ) -> None:
        """订阅 Topic/Queue 并注册业务回调

        Args:
            topic: 订阅的 Topic / Queue
            group_id: 消费者组 ID（Kafka consumer group / RabbitMQ 同 queue 多消费者）
            callback: 异步回调函数 (message_body, metadata) -> None
            from_beginning: 是否从最早消息开始消费
        """
        pass

    @abstractmethod
    async def start(self) -> None:
        """启动消费循环"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """停止消费循环并释放资源"""
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """消费者是否正在运行"""
        pass
