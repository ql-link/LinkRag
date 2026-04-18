"""
RabbitMQ Vendor Adapter

实现 IMQSender / IMQReceiver，底层封装 aio-pika (AMQP 0.9.1)。
保持 RabbitMQ 原生语义：Exchange、Queue、Binding、RoutingKey、延迟消息。
不将 Kafka 的 Partition/Offset 概念强加给 RabbitMQ（遵循 SKILL.md 设计规则）。
"""
import asyncio
import json
from typing import Any, Callable, Awaitable, Dict, List, Optional

from loguru import logger

from src.core.mq.interfaces import IMQSender, IMQReceiver
from src.core.mq.exceptions import (
    MQConnectionError,
    MQSendError,
    MQConsumeError,
)


class RabbitMQSender(IMQSender):
    """RabbitMQ 消息生产者

    底层使用 aio-pika。
    支持直连交换器发送、延迟消息（需 rabbitmq_delayed_message_exchange 插件）。
    """

    def __init__(
        self,
        url: str,
        *,
        exchange_name: str = "",
        exchange_type: str = "direct",
        durable: bool = True,
        delivery_mode: int = 2,
        confirm_delivery: bool = True,
    ):
        """
        Args:
            url: AMQP 连接 URL (amqp://user:pass@host:port/vhost)
            exchange_name: 目标交换器名称（空字符串 = 默认交换器）
            exchange_type: 交换器类型 (direct / fanout / topic / headers)
            durable: 交换器/队列是否持久化
            delivery_mode: 消息投递模式 (1=非持久化, 2=持久化)
            confirm_delivery: 是否开启 publisher confirms
        """
        self._url = url
        self._exchange_name = exchange_name
        self._exchange_type = exchange_type
        self._durable = durable
        self._delivery_mode = delivery_mode
        self._confirm_delivery = confirm_delivery

        self._connection = None
        self._channel = None
        self._exchange = None

    async def _ensure_connection(self) -> None:
        """懒初始化连接、Channel 和 Exchange"""
        if self._connection and not self._connection.is_closed:
            return
        try:
            import aio_pika

            self._connection = await aio_pika.connect_robust(self._url)
            self._channel = await self._connection.channel()

            if self._confirm_delivery:
                await self._channel.set_qos(prefetch_count=1)

            # 声明交换器（空名称使用 RabbitMQ 默认交换器，不需要显式声明）
            if self._exchange_name:
                self._exchange = await self._channel.declare_exchange(
                    self._exchange_name,
                    type=self._exchange_type,
                    durable=self._durable,
                )
            else:
                self._exchange = self._channel.default_exchange

            logger.info(f"[RabbitMQ Producer] 连接成功: {self._url}")
        except ImportError:
            raise MQConnectionError(
                "aio-pika 未安装，请执行: pip install aio-pika",
                vendor="rabbitmq",
            )
        except Exception as e:
            self._connection = None
            raise MQConnectionError(
                f"RabbitMQ 连接失败: {e}",
                vendor="rabbitmq",
            ) from e

    async def send(
        self,
        topic: str,
        message: str,
        *,
        key: str | None = None,
        headers: Dict[str, str] | None = None,
        delay_ms: int | None = None,
    ) -> None:
        """发送消息到 RabbitMQ

        Args:
            topic: Queue 名称（作为 routing_key 使用）
            message: 消息体
            key: routing_key 覆盖（优先于 topic）
            headers: AMQP 消息头
            delay_ms: 延迟毫秒数（需 delayed_message_exchange 插件）
        """
        await self._ensure_connection()
        try:
            import aio_pika

            routing_key = key or topic

            msg_headers = dict(headers) if headers else {}
            if delay_ms is not None and delay_ms > 0:
                msg_headers["x-delay"] = str(delay_ms)

            amqp_message = aio_pika.Message(
                body=message.encode("utf-8"),
                delivery_mode=self._delivery_mode,
                content_type="application/json",
                headers=msg_headers if msg_headers else None,
            )

            # 确保队列存在（声明幂等）
            if not self._exchange_name:
                await self._channel.declare_queue(
                    topic, durable=self._durable
                )

            await self._exchange.publish(
                amqp_message,
                routing_key=routing_key,
            )
            logger.debug(
                f"[RabbitMQ] 消息已发送 -> routing_key={routing_key}"
            )
        except Exception as e:
            raise MQSendError(
                f"RabbitMQ 消息发送失败: routing_key={key or topic}, error={e}",
                vendor="rabbitmq",
            ) from e

    async def send_batch(
        self,
        topic: str,
        messages: List[str],
        *,
        keys: List[str | None] | None = None,
    ) -> None:
        """批量发送（RabbitMQ 没有原生 batch API，逐条发送）"""
        if keys and len(keys) != len(messages):
            raise MQSendError(
                f"keys 长度 ({len(keys)}) 与 messages 长度 ({len(messages)}) 不一致",
                vendor="rabbitmq",
            )
        for i, msg in enumerate(messages):
            await self.send(
                topic=topic,
                message=msg,
                key=keys[i] if keys else None,
            )

    async def close(self) -> None:
        """关闭连接"""
        if self._connection and not self._connection.is_closed:
            await self._connection.close()
            self._connection = None
            self._channel = None
            self._exchange = None
            logger.info("[RabbitMQ Producer] 已关闭")


class RabbitMQReceiver(IMQReceiver):
    """RabbitMQ 消息消费者

    底层使用 aio-pika 的 push 模式（basic_consume）。
    支持多 Queue 订阅、手动 ACK、消费者预取控制。
    """

    def __init__(
        self,
        url: str,
        *,
        prefetch_count: int = 10,
        durable: bool = True,
        auto_delete: bool = False,
        exclusive: bool = False,
    ):
        self._url = url
        self._prefetch_count = prefetch_count
        self._durable = durable
        self._auto_delete = auto_delete
        self._exclusive = exclusive

        self._connection = None
        self._channel = None
        self._subscriptions: List[Dict[str, Any]] = []
        self._consumer_tags: List[str] = []
        self._running = False

    async def subscribe(
        self,
        topic: str,
        group_id: str,
        callback: Callable[[str, Dict[str, Any]], Awaitable[None]],
        *,
        from_beginning: bool = False,
    ) -> None:
        """注册 Queue 订阅

        Args:
            topic: Queue 名称
            group_id: 消费者标签（RabbitMQ 中同一 queue 的多个消费者天然是竞争消费）
            callback: 业务回调
            from_beginning: 在 RabbitMQ 中无实际意义（消息一旦 ACK 即删除）
        """
        self._subscriptions.append({
            "queue_name": topic,
            "consumer_tag": f"{group_id}_{topic}",
            "callback": callback,
        })
        logger.info(
            f"[RabbitMQ Consumer] 注册订阅: queue={topic}, tag={group_id}"
        )

    async def start(self) -> None:
        """启动消费"""
        if self._running:
            logger.warning("[RabbitMQ Consumer] 已在运行中")
            return
        if not self._subscriptions:
            raise MQConsumeError("没有注册任何订阅", vendor="rabbitmq")

        try:
            import aio_pika

            self._connection = await aio_pika.connect_robust(self._url)
            self._channel = await self._connection.channel()
            await self._channel.set_qos(prefetch_count=self._prefetch_count)

            for sub in self._subscriptions:
                queue = await self._channel.declare_queue(
                    sub["queue_name"],
                    durable=self._durable,
                    auto_delete=self._auto_delete,
                    exclusive=self._exclusive,
                )

                # 使用闭包绑定 callback
                cb = sub["callback"]
                consumer_tag = sub["consumer_tag"]

                async def _on_message(
                    message: aio_pika.IncomingMessage,
                    _cb=cb,
                ) -> None:
                    async with message.process():
                        body = message.body.decode("utf-8")
                        metadata = {
                            "queue": message.routing_key,
                            "exchange": message.exchange or "",
                            "routing_key": message.routing_key,
                            "delivery_tag": message.delivery_tag,
                            "message_id": message.message_id,
                            "timestamp": (
                                message.timestamp.timestamp()
                                if message.timestamp else None
                            ),
                            "headers": dict(message.headers) if message.headers else {},
                        }
                        try:
                            await _cb(body, metadata)
                        except Exception as e:
                            logger.error(
                                f"[RabbitMQ] 业务回调异常: "
                                f"queue={message.routing_key}, error={e}"
                            )
                            # message.process() 上下文管理器会自动 nack
                            raise

                await queue.consume(_on_message, consumer_tag=consumer_tag)
                self._consumer_tags.append(consumer_tag)

            self._running = True
            logger.info(
                f"[RabbitMQ Consumer] 启动成功: "
                f"queues={[s['queue_name'] for s in self._subscriptions]}"
            )

        except ImportError:
            raise MQConnectionError(
                "aio-pika 未安装，请执行: pip install aio-pika",
                vendor="rabbitmq",
            )
        except Exception as e:
            self._running = False
            raise MQConnectionError(
                f"RabbitMQ Consumer 启动失败: {e}",
                vendor="rabbitmq",
            ) from e

    async def stop(self) -> None:
        """停止消费并关闭连接"""
        self._running = False
        if self._channel:
            for tag in self._consumer_tags:
                try:
                    await self._channel.cancel(tag)
                except Exception:
                    pass
            self._consumer_tags.clear()
        if self._connection and not self._connection.is_closed:
            await self._connection.close()
            self._connection = None
            self._channel = None
        logger.info("[RabbitMQ Consumer] 已停止")

    def is_running(self) -> bool:
        return self._running
