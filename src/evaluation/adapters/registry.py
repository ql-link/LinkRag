# -*- coding: utf-8 -*-
"""
EvaluableRegistry — 全局 Evaluable 注册表。

Pipeline YAML 中的 evaluable name 通过此表解析为实例，
Runner 和 Evaluator 不直接引用业务类。

设计：
- 类变量 _store 保证进程级单例。
- 新增解析后端 / 分片策略 → 只需 register(ParserAdapter(...)) 一行。
- 不存在时抛 KeyError，比返回 None 更容易定位配置错误。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.evaluation.contracts.evaluable import Evaluable


class EvaluableRegistry:
    """全局 Evaluable 注册表（进程级单例，类变量实现）。

    Pipeline YAML 中的字符串 name 通过此表解析为具体实例，
    Runner / Evaluator 永远不直接引用业务类。
    """

    _store: dict[str, "Evaluable"] = {}

    @classmethod
    def register(cls, evaluable: "Evaluable") -> None:
        """注册一个 Evaluable 实例。

        若同名已存在则覆盖（方便测试时替换 mock）。

        Args:
            evaluable: 实现了 Evaluable 协议的实例。
        """
        cls._store[evaluable.name] = evaluable

    @classmethod
    def get(cls, name: str) -> "Evaluable":
        """按名称获取已注册的 Evaluable 实例。

        Args:
            name: Evaluable.name 字符串。

        Returns:
            Evaluable: 对应的实例。

        Raises:
            KeyError: name 未注册时，提示应在 adapters/ 中注册。
        """
        if name not in cls._store:
            registered = list(cls._store.keys())
            raise KeyError(
                f"Evaluable {name!r} 未注册。"
                f"请在 adapters/ 中调用 EvaluableRegistry.register(...)。"
                f"已注册: {registered}"
            )
        return cls._store[name]

    @classmethod
    def all_for_stage(cls, stage: str) -> list["Evaluable"]:
        """获取指定 stage 的所有已注册 Evaluable。

        Args:
            stage: stage 名称，如 "parse" / "chunk" / "embed"。

        Returns:
            list[Evaluable]: 属于该 stage 的所有 evaluable 列表。
        """
        return [e for e in cls._store.values() if e.stage == stage]

    @classmethod
    def all(cls) -> list["Evaluable"]:
        """返回所有已注册的 Evaluable。

        Returns:
            list[Evaluable]: 全部已注册实例。
        """
        return list(cls._store.values())

    @classmethod
    def clear(cls) -> None:
        """清空注册表（主要用于测试隔离）。"""
        cls._store.clear()
