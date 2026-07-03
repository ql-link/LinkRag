"""
MQ Service 服务层

提供面向业务的高层 API，封装 Factory → Sender/Receiver 的调用链。
业务代码只依赖 MQService，不直接操作 Factory 或 Vendor Adapter。

Pipeline: BusinessCode → MQService.send(msg) → Factory.get_sender() → VendorAdapter.send()
"""

from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger

from src.core.mq.factory import MQFactory
from src.core.mq.message import AbstractMessage
from src.observability.tracing import (
    TRACE_ID_HEADER,
    extract_trace_id_from_metadata,
    get_trace_id,
    trace_context,
)


class MQService:
    """MQ 消息服务

    使用方式：
        mq = MQService()

        # 发送消息
        msg = ParseTaskMessage.build(task_id="xxx", ...)
        await mq.send(msg)

        # 注册消费者并启动
        await mq.subscribe("tolink.rag.parse_task", "parse-group", handler)
        await mq.start_consuming()
    """

    def __init__(self, factory: Optional[MQFactory] = None):
        self._factory = factory or MQFactory()

    @staticmethod
    def _headers_with_current_trace(headers: Dict[str, str] | None = None) -> Dict[str, str] | None:
        trace_id = get_trace_id()
        if not trace_id:
            return headers

        merged = dict(headers) if headers else {}
        merged.setdefault(TRACE_ID_HEADER, trace_id)
        return merged

    async def send(self, message: AbstractMessage) -> None:
        """发送业务消息

        对应 SKILL.md 中的 mqSend.send(MyMQ.build(...))

        Args:
            message: AbstractMessage 的具体子类实例
        """
        sender = self._factory.get_sender()
        topic = message.get_mq_name()
        serialized = message.serialize()
        routing_key = message.get_routing_key()

        await sender.send(
            topic=topic,
            message=serialized,
            key=routing_key,
            headers=self._headers_with_current_trace(),
        )
        mq_type = message.get_mq_type()
        logger.info(f"[MQService] 消息已发送: type={mq_type}, topic={topic}")

    async def send_raw(
        self,
        topic: str,
        message: str,
        *,
        key: str | None = None,
        headers: Dict[str, str] | None = None,
    ) -> None:
        """发送原始消息（不走 AbstractMessage 封装）

        适用于对接外部系统的非标准消息格式。
        """
        sender = self._factory.get_sender()
        await sender.send(
            topic=topic,
            message=message,
            key=key,
            headers=self._headers_with_current_trace(headers),
        )

    async def subscribe(
        self,
        topic: str,
        group_id: str,
        callback: Callable[[str, Dict[str, Any]], Awaitable[None]],
        *,
        from_beginning: bool = False,
    ) -> None:
        """注册消息订阅

        Args:
            topic: Topic / Queue 名称
            group_id: 消费者组 ID
            callback: 异步回调 (message_body, metadata)
            from_beginning: 是否从最早消息开始
        """
        receiver = self._factory.get_receiver()

        async def traced_callback(message_body: str, metadata: Dict[str, Any]) -> None:
            trace_id = extract_trace_id_from_metadata(metadata)
            if not trace_id:
                await callback(message_body, metadata)
                return

            with trace_context(trace_id):
                await callback(message_body, metadata)

        await receiver.subscribe(
            topic=topic,
            group_id=group_id,
            callback=traced_callback,
            from_beginning=from_beginning,
        )

    async def start_consuming(self) -> None:
        """启动消费循环"""
        receiver = self._factory.get_receiver()
        await receiver.start()
        logger.info("[MQService] 消费者已启动")

    async def stop_consuming(self) -> None:
        """停止消费"""
        receiver = self._factory.get_receiver()
        await receiver.stop()
        logger.info("[MQService] 消费者已停止")

    async def close(self) -> None:
        """关闭所有 MQ 连接"""
        await self._factory.close_all()
