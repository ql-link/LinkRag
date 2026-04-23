"""
Kafka Vendor Adapter

实现 IMQSender / IMQReceiver，底层封装 aiokafka。
保持 Kafka 原生语义：Topic、Partition、ConsumerGroup、Offset。
不将 RabbitMQ 的 Exchange/Binding 概念强加给 Kafka（遵循 SKILL.md 设计规则）。
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


class KafkaSender(IMQSender):
    """Kafka 消息生产者

    底层使用 aiokafka.AIOKafkaProducer。
    支持异步发送、批量发送、指定 partition key。
    """

    def __init__(
        self,
        bootstrap_servers: str,
        *,
        client_id: str = "tolink-rag-producer",
        acks: str = "all",
        max_batch_size: int = 16384,
        linger_ms: int = 10,
        compression_type: str | None = "gzip",
        sasl_mechanism: str | None = None,
        sasl_plain_username: str | None = None,
        sasl_plain_password: str | None = None,
        security_protocol: str = "PLAINTEXT",
    ):
        self._bootstrap_servers = bootstrap_servers
        self._client_id = client_id
        self._acks = acks
        self._max_batch_size = max_batch_size
        self._linger_ms = linger_ms
        self._compression_type = compression_type
        self._sasl_mechanism = sasl_mechanism
        self._sasl_plain_username = sasl_plain_username
        self._sasl_plain_password = sasl_plain_password
        self._security_protocol = security_protocol
        self._producer = None

    async def _ensure_producer(self) -> None:
        """懒初始化 Producer，避免在 import 时就连接 Broker"""
        if self._producer is not None:
            return
        try:
            from aiokafka import AIOKafkaProducer

            kwargs: Dict[str, Any] = {
                "bootstrap_servers": self._bootstrap_servers,
                "client_id": self._client_id,
                "acks": self._acks,
                "max_batch_size": self._max_batch_size,
                "linger_ms": self._linger_ms,
                "value_serializer": lambda v: v.encode("utf-8"),
                "key_serializer": lambda k: k.encode("utf-8") if k else None,
                "security_protocol": self._security_protocol,
            }
            if self._compression_type:
                kwargs["compression_type"] = self._compression_type
            if self._sasl_mechanism:
                kwargs["sasl_mechanism"] = self._sasl_mechanism
                kwargs["sasl_plain_username"] = self._sasl_plain_username
                kwargs["sasl_plain_password"] = self._sasl_plain_password

            self._producer = AIOKafkaProducer(**kwargs)
            await self._producer.start()
            logger.info(
                f"[Kafka Producer] 连接成功: {self._bootstrap_servers}"
            )
        except ImportError:
            raise MQConnectionError(
                "aiokafka 未安装，请执行: pip install aiokafka",
                vendor="kafka",
            )
        except Exception as e:
            self._producer = None
            raise MQConnectionError(
                f"Kafka Producer 连接失败: {e}",
                vendor="kafka",
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
        """发送单条消息到 Kafka Topic

        注意：Kafka 原生不支持延迟消息，delay_ms 参数会被记录到 headers 中，
        由消费端自行实现延迟逻辑（如写入延迟表后轮询）。
        """
        await self._ensure_producer()
        try:
            kafka_headers = None
            if headers or delay_ms:
                raw_headers = headers or {}
                if delay_ms is not None:
                    raw_headers["x-delay-ms"] = str(delay_ms)
                kafka_headers = [
                    (k, v.encode("utf-8")) for k, v in raw_headers.items()
                ]

            await self._producer.send_and_wait(
                topic=topic,
                value=message,
                key=key,
                headers=kafka_headers,
            )
            logger.debug(f"[Kafka] 消息已发送 -> topic={topic}, key={key}")
        except Exception as e:
            raise MQSendError(
                f"Kafka 消息发送失败: topic={topic}, error={e}",
                vendor="kafka",
            ) from e

    async def send_batch(
        self,
        topic: str,
        messages: List[str],
        *,
        keys: List[str | None] | None = None,
    ) -> None:
        """批量发送消息（利用 Kafka batch 机制）"""
        await self._ensure_producer()
        if keys and len(keys) != len(messages):
            raise MQSendError(
                f"keys 长度 ({len(keys)}) 与 messages 长度 ({len(messages)}) 不一致",
                vendor="kafka",
            )
        try:
            batch = self._producer.create_batch()
            for i, msg in enumerate(messages):
                key = keys[i] if keys else None
                # create_batch 是同步 API，逐条追加
                metadata = batch.append(
                    key=key.encode("utf-8") if key else None,
                    value=msg.encode("utf-8"),
                    headers=None,
                )
                if metadata is None:
                    # batch 满了，先发送再创建新 batch
                    await self._producer.send_and_wait(topic, value=msg, key=key)
                    logger.debug(
                        f"[Kafka] batch 溢出，回退到单条发送: msg_index={i}"
                    )
            # 发送 batch 中剩余的消息
            partitions = await self._producer.partitions_for(topic)
            if partitions and batch.record_count() > 0:
                partition = list(partitions)[0]
                from aiokafka import TopicPartition
                tp = TopicPartition(topic, partition)
                await self._producer.send_batch(batch, tp)
            logger.debug(
                f"[Kafka] 批量发送完成: topic={topic}, count={len(messages)}"
            )
        except MQSendError:
            raise
        except Exception as e:
            raise MQSendError(
                f"Kafka 批量发送失败: topic={topic}, error={e}",
                vendor="kafka",
            ) from e

    async def close(self) -> None:
        """关闭 Producer"""
        if self._producer:
            await self._producer.stop()
            self._producer = None
            logger.info("[Kafka Producer] 已关闭")


class KafkaReceiver(IMQReceiver):
    """Kafka 消息消费者

    底层使用 aiokafka.AIOKafkaConsumer。
    每个 Receiver 实例对应一个 ConsumerGroup，支持多 Topic 订阅。
    """

    def __init__(
        self,
        bootstrap_servers: str,
        *,
        client_id: str = "tolink-rag-consumer",
        auto_offset_reset: str = "latest",
        enable_auto_commit: bool = False,
        max_poll_records: int = 100,
        max_poll_interval_ms: int = 900000,
        session_timeout_ms: int = 30000,
        heartbeat_interval_ms: int = 10000,
        sasl_mechanism: str | None = None,
        sasl_plain_username: str | None = None,
        sasl_plain_password: str | None = None,
        security_protocol: str = "PLAINTEXT",
    ):
        self._bootstrap_servers = bootstrap_servers
        self._client_id = client_id
        self._auto_offset_reset = auto_offset_reset
        self._enable_auto_commit = enable_auto_commit
        self._max_poll_records = max_poll_records
        self._max_poll_interval_ms = max_poll_interval_ms
        self._session_timeout_ms = session_timeout_ms
        self._heartbeat_interval_ms = heartbeat_interval_ms
        self._sasl_mechanism = sasl_mechanism
        self._sasl_plain_username = sasl_plain_username
        self._sasl_plain_password = sasl_plain_password
        self._security_protocol = security_protocol

        self._consumer = None
        self._subscriptions: List[Dict[str, Any]] = []
        self._running = False
        self._consume_task: Optional[asyncio.Task] = None

    async def subscribe(
        self,
        topic: str,
        group_id: str,
        callback: Callable[[str, Dict[str, Any]], Awaitable[None]],
        *,
        from_beginning: bool = False,
    ) -> None:
        """注册 Topic 订阅（延迟到 start() 时生效）"""
        self._subscriptions.append({
            "topic": topic,
            "group_id": group_id,
            "callback": callback,
            "from_beginning": from_beginning,
        })
        logger.info(
            f"[Kafka Consumer] 注册订阅: topic={topic}, group={group_id}"
        )

    async def start(self) -> None:
        """启动消费循环"""
        if self._running:
            logger.warning("[Kafka Consumer] 已在运行中，跳过重复启动")
            return
        if not self._subscriptions:
            raise MQConsumeError("没有注册任何订阅", vendor="kafka")

        try:
            from aiokafka import AIOKafkaConsumer

            # 使用第一个订阅的 group_id（同一个 Receiver 通常属于同一个 group）
            primary = self._subscriptions[0]
            topics = [sub["topic"] for sub in self._subscriptions]

            offset_reset = (
                "earliest" if primary["from_beginning"]
                else self._auto_offset_reset
            )

            kwargs: Dict[str, Any] = {
                "bootstrap_servers": self._bootstrap_servers,
                "client_id": self._client_id,
                "group_id": primary["group_id"],
                "auto_offset_reset": offset_reset,
                "enable_auto_commit": self._enable_auto_commit,
                "max_poll_records": self._max_poll_records,
                "max_poll_interval_ms": self._max_poll_interval_ms,
                "session_timeout_ms": self._session_timeout_ms,
                "heartbeat_interval_ms": self._heartbeat_interval_ms,
                "value_deserializer": lambda v: v.decode("utf-8"),
                "security_protocol": self._security_protocol,
            }
            if self._sasl_mechanism:
                kwargs["sasl_mechanism"] = self._sasl_mechanism
                kwargs["sasl_plain_username"] = self._sasl_plain_username
                kwargs["sasl_plain_password"] = self._sasl_plain_password

            self._consumer = AIOKafkaConsumer(*topics, **kwargs)
            await self._consumer.start()
            self._running = True
            logger.info(
                f"[Kafka Consumer] 启动成功: topics={topics}, "
                f"group={primary['group_id']}"
            )

            # 启动后台消费协程
            self._consume_task = asyncio.create_task(self._consume_loop())

        except ImportError:
            raise MQConnectionError(
                "aiokafka 未安装，请执行: pip install aiokafka",
                vendor="kafka",
            )
        except Exception as e:
            self._running = False
            raise MQConnectionError(
                f"Kafka Consumer 启动失败: {e}",
                vendor="kafka",
            ) from e

    async def _consume_loop(self) -> None:
        """消费主循环"""
        # 构建 topic -> callback 映射
        callback_map: Dict[str, Callable] = {
            sub["topic"]: sub["callback"] for sub in self._subscriptions
        }

        try:
            async for msg in self._consumer:
                if not self._running:
                    break
                topic = msg.topic
                cb = callback_map.get(topic)
                if not cb:
                    logger.warning(f"[Kafka] 收到未注册 Topic 的消息: {topic}")
                    continue

                metadata = {
                    "topic": topic,
                    "partition": msg.partition,
                    "offset": msg.offset,
                    "timestamp": msg.timestamp,
                    "key": msg.key.decode("utf-8") if msg.key else None,
                    "headers": (
                        {k: v.decode("utf-8") for k, v in msg.headers}
                        if msg.headers else {}
                    ),
                }
                try:
                    await cb(msg.value, metadata)
                    # 手动提交 offset（at-least-once 语义）
                    if not self._enable_auto_commit:
                        await self._consumer.commit()
                except Exception as e:
                    logger.error(
                        f"[Kafka] 业务回调异常: topic={topic}, "
                        f"offset={msg.offset}, error={e}"
                    )
                    # 不提交 offset，消息将被重新消费
        except asyncio.CancelledError:
            logger.info("[Kafka Consumer] 消费循环被取消")
        except Exception as e:
            if self._running:
                logger.error(f"[Kafka Consumer] 消费循环异常退出: {e}")

    async def stop(self) -> None:
        """停止消费"""
        self._running = False
        if self._consume_task and not self._consume_task.done():
            self._consume_task.cancel()
            try:
                await self._consume_task
            except asyncio.CancelledError:
                pass
        if self._consumer:
            await self._consumer.stop()
            self._consumer = None
            logger.info("[Kafka Consumer] 已停止")

    def is_running(self) -> bool:
        return self._running
