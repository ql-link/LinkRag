# -*- coding: utf-8 -*-
"""
Hook Protocol + EvalEvent — 可观测性事件系统。

Runner 在关键节点广播 EvalEvent，Hook 列表在 pipeline YAML 中声明。
默认附带 LoggingHook + ProgressHook，可扩展为 Webhook / 飞书通知。
评估过程的可观测性完全内聚，不依赖业务日志体系。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol


# 标准事件类型常量
EVENT_RUN_START = "run_start"
EVENT_STAGE_START = "stage_start"
EVENT_SAMPLE_DONE = "sample_done"
EVENT_STAGE_DONE = "stage_done"
EVENT_RUN_COMPLETE = "run_complete"
EVENT_ERROR = "error"

ALL_EVENT_TYPES = frozenset([
    EVENT_RUN_START,
    EVENT_STAGE_START,
    EVENT_SAMPLE_DONE,
    EVENT_STAGE_DONE,
    EVENT_RUN_COMPLETE,
    EVENT_ERROR,
])


@dataclass
class EvalEvent:
    """评估过程广播事件。

    Runner 在关键节点构造并广播此事件，所有注册的 Hook 都会收到。

    Attributes:
        event_type: 事件类型，见 EVENT_* 常量。
        timestamp:  事件发生时间戳（Unix 秒，perf_counter 精度）。
        payload:    事件附加数据，各事件类型携带不同字段：
                    - run_start:     {"run_id", "dataset_name", "pipeline_config"}
                    - stage_start:   {"run_id", "stage", "evaluable_count"}
                    - sample_done:   {"run_id", "stage", "sample_id", "success", "elapsed_ms"}
                    - stage_done:    {"run_id", "stage", "total", "success_count"}
                    - run_complete:  {"run_id", "total_samples", "elapsed_s"}
                    - error:         {"run_id", "stage", "sample_id", "error", "error_type"}
    """
    event_type: str
    timestamp: float = field(default_factory=time.time)
    payload: dict = field(default_factory=dict)


class Hook(Protocol):
    """事件钩子协议。

    实现者订阅特定或全部事件类型，在 on_event 中执行副作用。
    Hook 是异步的，阻塞操作应在 Hook 内部用 asyncio.to_thread 隔离。
    Runner 串行调用所有 Hook，单个 Hook 异常不应影响评估流程（实现者自行 catch）。
    """

    async def on_event(self, event: EvalEvent) -> None:
        """处理广播事件。

        Args:
            event: 评估过程广播的事件对象。
        """
        ...
