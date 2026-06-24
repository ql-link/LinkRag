"""单轮 workflow run 的产物上下文。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class WorkflowContext:
    """保存本轮 run 内可被下游消费的产物。"""

    def __init__(self, initial_products: Mapping[str, Any] | None = None):
        self._products: dict[str, Any] = dict(initial_products or {})

    def set(self, key: str, value: Any) -> None:
        self._products[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._products.get(key, default)

    def require(self, key: str) -> Any:
        if key not in self._products:
            raise KeyError(f"workflow product not found: {key}")
        return self._products[key]

    def has(self, key: str) -> bool:
        return key in self._products

    def available_keys(self) -> set[str]:
        return set(self._products)

    def snapshot(self) -> dict[str, Any]:
        return dict(self._products)
