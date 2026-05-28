"""召回 pipeline 单测共用 fixtures。

提供 FakeRetriever：可配置返回固定列表、抛固定异常、或记录调用时序。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from src.core.pipeline.recall import RetrieverHit


@dataclass
class FakeRetriever:
    """可控的召回路替身。

    用法：
        retriever = FakeRetriever(source="dense", hits=[RetrieverHit(...)])
        retriever = FakeRetriever(source="dense", exc=RuntimeError("qdrant timeout"))
    """

    source: str
    hits: list[RetrieverHit] | None = None
    exc: Exception | None = None
    # 模拟耗时：用于串行 / 并行顺序观察。
    delay_seconds: float = 0.0
    # 测试断言用：记录每次 recall 的入参与触发时机。
    calls: list[tuple[str, list[int], list[int] | None]] = field(default_factory=list)
    call_order: list[float] = field(default_factory=list)
    # 注入一个共享的"全局调用序号"生成器以观察跨实例的触发顺序。
    sequence_recorder: list[str] | None = None

    async def recall(
        self,
        query: str,
        dataset_ids: list[int],
        doc_ids: list[int] | None = None,
    ) -> list[RetrieverHit]:
        import time as _time
        self.calls.append((query, list(dataset_ids), list(doc_ids) if doc_ids else None))
        self.call_order.append(_time.monotonic())
        if self.sequence_recorder is not None:
            self.sequence_recorder.append(self.source)
        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)
        if self.exc is not None:
            raise self.exc
        return list(self.hits or [])
