# -*- coding: utf-8 -*-
"""LoggingHook — 默认日志 Hook，将评估事件输出到独立 logger。"""
from __future__ import annotations

import logging

from src.evaluation.contracts.hook import (
    EvalEvent, EVENT_RUN_START, EVENT_RUN_COMPLETE,
    EVENT_STAGE_START, EVENT_STAGE_DONE, EVENT_SAMPLE_DONE, EVENT_ERROR,
)

_logger = logging.getLogger("evaluation.hook.logging")


class LoggingHook:
    """将评估事件以结构化日志输出到 evaluation.hook.logging logger。

    使用独立 logger 保证评估可观测性不依赖业务日志体系。
    """

    async def on_event(self, event: EvalEvent) -> None:
        """处理评估事件，按类型输出不同级别日志。

        Args:
            event: 评估事件对象。
        """
        et = event.event_type
        p = event.payload

        if et == EVENT_RUN_START:
            _logger.info(
                "[RUN_START] run_id=%s dataset=%s samples=%s",
                p.get("run_id"), p.get("dataset_name"), p.get("sample_count"),
            )
        elif et == EVENT_STAGE_START:
            _logger.debug(
                "[STAGE_START] run=%s stage=%s sample=%s evaluables=%s",
                p.get("run_id"), p.get("stage"), p.get("sample_id"), p.get("evaluable_count"),
            )
        elif et == EVENT_SAMPLE_DONE:
            level = logging.DEBUG if p.get("success") else logging.WARNING
            _logger.log(
                level,
                "[SAMPLE_DONE] run=%s stage=%s sample=%s success=%s elapsed=%.1fms",
                p.get("run_id"), p.get("stage"), p.get("sample_id"),
                p.get("success"), p.get("elapsed_ms", 0),
            )
        elif et == EVENT_STAGE_DONE:
            _logger.info(
                "[STAGE_DONE] run=%s stage=%s",
                p.get("run_id"), p.get("stage"),
            )
        elif et == EVENT_RUN_COMPLETE:
            _logger.info(
                "[RUN_COMPLETE] run=%s total_samples=%s elapsed=%.1fs",
                p.get("run_id"), p.get("total_samples"), p.get("elapsed_s", 0),
            )
        elif et == EVENT_ERROR:
            _logger.error(
                "[ERROR] run=%s stage=%s sample=%s type=%s err=%s",
                p.get("run_id"), p.get("stage"), p.get("sample_id"),
                p.get("error_type"), p.get("error"),
            )
