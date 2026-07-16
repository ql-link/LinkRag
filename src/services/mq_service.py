"""
MQ Service 服务层

提供面向业务的高层 API，封装 Factory → Sender/Receiver 的调用链。
业务代码只依赖 MQService，不直接操作 Factory 或 Vendor Adapter。

Pipeline: BusinessCode → MQService.send(msg) → Factory.get_sender() → VendorAdapter.send()
"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger

from src.core.mq.factory import MQFactory
from src.core.mq.message import AbstractMessage
from src.core.mq.observability import (
    compact_log_value,
    format_log_fields,
    message_size_bytes,
    monotonic_duration_ms,
)
from src.observability.logging import safe_exception_stack, truncate_log_value
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
    def _resolve_log_fields(
        message: AbstractMessage,
        *,
        message_type: str,
        topic: str,
    ) -> Dict[str, object]:
        """读取消息白名单摘要；观测代码异常不能阻断实际发送。"""
        try:
            return message.get_log_fields()
        except Exception as exc:
            logger.bind(
                event="mq_log_fields_failed",
                outcome="failed",
                message_type=message_type,
                topic=topic,
                error_type=type(exc).__name__,
                error_message=truncate_log_value(exc),
                stack_trace=safe_exception_stack(exc),
            ).warning(
                "[MQ] mq_log_fields_failed type={} topic={} error_type={} error={}",
                message_type,
                compact_log_value(topic),
                type(exc).__name__,
                compact_log_value(exc),
            )
            return {}

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
        topic = message.get_mq_name()
        message_type = message.get_mq_type()
        routing_key = message.get_routing_key()
        log_field_values = self._resolve_log_fields(
            message,
            message_type=message_type,
            topic=topic,
        )
        log_fields = format_log_fields(log_field_values)
        started_at = time.monotonic()
        serialized = ""

        logger.bind(
            event="mq_send_started",
            outcome="processing",
            message_type=message_type,
            topic=topic,
            routing_key=routing_key or "",
            **log_field_values,
        ).debug(
            "[MQ] mq_send_started type={} topic={} routing_key={} {}",
            message_type,
            compact_log_value(topic),
            compact_log_value(routing_key),
            log_fields,
        )
        try:
            serialized = message.serialize()
            sender = self._factory.get_sender()
            await sender.send(
                topic=topic,
                message=serialized,
                key=routing_key,
                headers=self._headers_with_current_trace(),
            )
        except Exception as exc:
            duration_ms = monotonic_duration_ms(started_at)
            logger.bind(
                event="mq_send_failed",
                outcome="failed",
                message_type=message_type,
                topic=topic,
                routing_key=routing_key or "",
                duration_ms=duration_ms,
                message_bytes=message_size_bytes(serialized),
                error_type=type(exc).__name__,
                error_message=truncate_log_value(exc),
                stack_trace=safe_exception_stack(exc),
                **log_field_values,
            ).error(
                "[MQ] mq_send_failed type={} topic={} routing_key={} duration_ms={} "
                "message_bytes={} error_type={} error={} {}",
                message_type,
                compact_log_value(topic),
                compact_log_value(routing_key),
                duration_ms,
                message_size_bytes(serialized),
                type(exc).__name__,
                compact_log_value(exc),
                log_fields,
            )
            raise

        duration_ms = monotonic_duration_ms(started_at)
        logger.bind(
            event="mq_send_succeeded",
            outcome="success",
            message_type=message_type,
            topic=topic,
            routing_key=routing_key or "",
            duration_ms=duration_ms,
            message_bytes=message_size_bytes(serialized),
            **log_field_values,
        ).info(
            "[MQ] mq_send_succeeded type={} topic={} routing_key={} duration_ms={} "
            "message_bytes={} {}",
            message_type,
            compact_log_value(topic),
            compact_log_value(routing_key),
            duration_ms,
            message_size_bytes(serialized),
            log_fields,
        )

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
        started_at = time.monotonic()
        merged_headers = self._headers_with_current_trace(headers)
        header_names = ",".join(sorted(merged_headers)) if merged_headers else "-"
        logger.bind(
            event="mq_raw_send_started",
            outcome="processing",
            topic=topic,
            routing_key=key or "",
            message_bytes=message_size_bytes(message),
            header_names=header_names,
        ).debug(
            "[MQ] mq_raw_send_started topic={} routing_key={} message_bytes={} " "header_names={}",
            compact_log_value(topic),
            compact_log_value(key),
            message_size_bytes(message),
            header_names,
        )
        try:
            sender = self._factory.get_sender()
            await sender.send(
                topic=topic,
                message=message,
                key=key,
                headers=merged_headers,
            )
        except Exception as exc:
            duration_ms = monotonic_duration_ms(started_at)
            logger.bind(
                event="mq_raw_send_failed",
                outcome="failed",
                topic=topic,
                routing_key=key or "",
                duration_ms=duration_ms,
                message_bytes=message_size_bytes(message),
                header_names=header_names,
                error_type=type(exc).__name__,
                error_message=truncate_log_value(exc),
                stack_trace=safe_exception_stack(exc),
            ).error(
                "[MQ] mq_raw_send_failed topic={} routing_key={} duration_ms={} "
                "message_bytes={} header_names={} error_type={} error={}",
                compact_log_value(topic),
                compact_log_value(key),
                duration_ms,
                message_size_bytes(message),
                header_names,
                type(exc).__name__,
                compact_log_value(exc),
            )
            raise

        duration_ms = monotonic_duration_ms(started_at)
        logger.bind(
            event="mq_raw_send_succeeded",
            outcome="success",
            topic=topic,
            routing_key=key or "",
            duration_ms=duration_ms,
            message_bytes=message_size_bytes(message),
            header_names=header_names,
        ).info(
            "[MQ] mq_raw_send_succeeded topic={} routing_key={} duration_ms={} "
            "message_bytes={} header_names={}",
            compact_log_value(topic),
            compact_log_value(key),
            duration_ms,
            message_size_bytes(message),
            header_names,
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
