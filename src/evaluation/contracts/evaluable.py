# -*- coding: utf-8 -*-
"""
Evaluable Protocol — 评估系统与 RAG 系统的唯一解耦点。

所有被评估对象（解析器、分片器、向量化器）必须通过 Adapter 实现本协议，
评估器 / Runner 只面向此协议编程，永远不直接引用业务类。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Any, runtime_checkable


@dataclass
class StageInput:
    """单次 stage 执行的输入容器。

    Attributes:
        sample_id: 数据集样本的唯一标识。
        payload:   本 stage 的主输入（bytes / str / ParseResult / list[Chunk]…）。
        context:   跨 stage 中间产物链，key 为上游 stage name。由 RunContext 填充，
                   Adapter 可按需从中读取上游产物（如 ParseResult）避免重复解析。
        run_index: 第几轮执行，多轮重跑时注入，用于稳定性指标（默认 0 = 第 1 轮）。
    """
    sample_id: str
    payload: Any
    context: dict = field(default_factory=dict)
    run_index: int = 0


@dataclass
class StageOutput:
    """单次 stage 执行的输出容器。

    Attributes:
        sample_id:  与 StageInput.sample_id 对应。
        payload:    本 stage 产物（解析 Markdown / Chunk 列表…），失败时为 None。
        elapsed_ms: 执行耗时（毫秒），用于延迟指标。
        success:    是否成功；失败时 payload=None，error 有值。
        error:      失败原因描述（类名 + 消息），成功时为 None。
        error_type: 异常类名，便于按类型分类统计（如 TimeoutError / OOMError）。
        extras:     任意附加信息（如 parser.metadata、chunk_count 等）。
        memory_mb:  可选峰值内存（tracemalloc 采集），超限时触发 OOM 标记。
    """
    sample_id: str
    payload: Any
    elapsed_ms: float
    success: bool
    error: str | None = None
    error_type: str | None = None
    # 修复 v1 可变默认值 bug：使用 field(default_factory=dict)
    extras: dict = field(default_factory=dict)
    memory_mb: float | None = None


@runtime_checkable
class Evaluable(Protocol):
    """被评估对象的统一外观接口。

    任何 RAG 模块（解析器 / 分片器 / 向量化器）要被评估，
    都通过 Adapter 实现此接口。评估器只对此接口编程。

    Attributes:
        name:  评估对象的唯一标识符，如 "parser.pdf.mineru"、"chunker.semantic"。
        stage: 所属 stage，如 "parse" | "enhance" | "chunk" | "embed"。
    """
    name: str
    stage: str

    async def run(self, item: StageInput) -> StageOutput:
        """异步执行本 stage，是必须实现的主入口。

        Args:
            item: 本次执行的输入容器。

        Returns:
            StageOutput: 执行结果，失败时 success=False 而非抛异常。
        """
        ...

    def run_sync(self, item: StageInput) -> StageOutput:
        """可选同步入口。

        RAG 系统解析入口多为同步函数，Adapter 可实现此方法避免不必要的异步包装。
        Runner 策略：
        - 有 event loop 时，通过 asyncio.to_thread(run_sync) 调用；
        - 无 loop 时，直接调用 run_sync；
        - 若 Adapter 未实现本方法，Runner 降级为 asyncio.run(run(item))。

        Args:
            item: 本次执行的输入容器。

        Returns:
            StageOutput: 执行结果。
        """
        ...
