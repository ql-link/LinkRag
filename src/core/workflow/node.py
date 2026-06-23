"""Workflow 节点抽象。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from src.core.workflow.context import WorkflowContext


class WorkflowNode(ABC):
    """声明式流程节点基类。

    业务节点只声明 requires/provides/allow_failure，并实现 run/restore。
    产物 key 和 output_ref 对框架均是不透明值。
    """

    def __init__(
        self,
        *,
        key: str,
        requires: Iterable[str] | None = None,
        provides: Iterable[str] | None = None,
        allow_failure: bool = False,
    ):
        if not key:
            raise ValueError("workflow node key must not be empty")
        self.key = key
        self.requires = tuple(requires or ())
        self.provides = tuple(provides or ())
        self.allow_failure = allow_failure

    @abstractmethod
    async def run(self, ctx: WorkflowContext) -> Any:
        """执行业务逻辑，返回可持久化的 output_ref。"""

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        """从 output_ref 恢复本节点 provides 的产物到 ctx。

        默认实现拒绝恢复，节点需要断点续跑时应显式覆盖。
        """

        raise NotImplementedError(f"node {self.key} does not implement restore()")
