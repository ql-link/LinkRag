from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from src.core.workflow import WorkflowContext, WorkflowNode


@dataclass
class WorkflowProbe:
    order: list[str] = field(default_factory=list)
    active: set[str] = field(default_factory=set)
    max_active: int = 0
    branch_simultaneous: bool = False
    branch_keys: set[str] = field(default_factory=set)
    consumed: dict[str, Any] = field(default_factory=dict)

    def enter(self, key: str) -> None:
        self.active.add(key)
        self.order.append(key)
        self.max_active = max(self.max_active, len(self.active))
        if self.branch_keys and self.branch_keys.issubset(self.active):
            self.branch_simultaneous = True

    def leave(self, key: str) -> None:
        self.active.discard(key)


class FakeNode(WorkflowNode):
    def __init__(
        self,
        key: str,
        *,
        requires: tuple[str, ...] = (),
        provides: tuple[str, ...] = (),
        allow_failure: bool = False,
        fail: bool = False,
        restore_fail: bool = False,
        delay: float = 0,
        probe: WorkflowProbe | None = None,
    ):
        super().__init__(
            key=key,
            requires=requires,
            provides=provides,
            allow_failure=allow_failure,
        )
        self.fail = fail
        self.restore_fail = restore_fail
        self.delay = delay
        self.probe = probe
        self.run_count = 0
        self.restore_count = 0

    async def run(self, ctx: WorkflowContext):
        self.run_count += 1
        if self.probe is not None:
            self.probe.enter(self.key)
            for product in self.requires:
                self.probe.consumed[f"{self.key}:{product}"] = ctx.get(product)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail:
                raise RuntimeError(f"{self.key} failed")
            for product in self.provides:
                ctx.set(product, f"{self.key}:{product}")
            return {"node": self.key}
        finally:
            if self.probe is not None:
                self.probe.leave(self.key)

    async def restore(self, ctx: WorkflowContext, output_ref):
        self.restore_count += 1
        if self.restore_fail:
            raise RuntimeError(f"{self.key} restore failed")
        for product in self.provides:
            ctx.set(product, f"restored:{product}")
