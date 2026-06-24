"""Workflow 定义、加载期校验与依赖推导。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from src.core.workflow._utils import topo_sort
from src.core.workflow.constants import ValidationErrorCode
from src.core.workflow.exceptions import WorkflowValidationError
from src.core.workflow.node import WorkflowNode


@dataclass(frozen=True)
class WorkflowDefinition:
    """一份已校验的 workflow 定义。"""

    name: str
    nodes: tuple[WorkflowNode, ...]
    initial_products: frozenset[str]
    biz_key: str | None = None

    @classmethod
    def from_nodes(
        cls,
        nodes: Iterable[WorkflowNode],
        *,
        name: str = "workflow",
        biz_key: str | None = None,
        initial_products: Iterable[str] | None = None,
    ) -> "WorkflowDefinition":
        definition = cls(
            name=name,
            biz_key=biz_key,
            nodes=tuple(nodes),
            initial_products=frozenset(initial_products or ()),
        )
        definition.validate()
        return definition

    @property
    def node_map(self) -> dict[str, WorkflowNode]:
        return {node.key: node for node in self.nodes}

    def validate(self) -> None:
        node_keys: set[str] = set()
        for node in self.nodes:
            if node.key in node_keys:
                raise WorkflowValidationError(
                    ValidationErrorCode.DUPLICATE_PRODUCER,
                    f"duplicate node key: {node.key}",
                )
            node_keys.add(node.key)

        producer_by_product: dict[str, WorkflowNode] = {}
        for node in self.nodes:
            for product in node.provides:
                previous = producer_by_product.get(product)
                if previous is not None:
                    raise WorkflowValidationError(
                        ValidationErrorCode.DUPLICATE_PRODUCER,
                        f'product "{product}" is provided by both '
                        f'"{previous.key}" and "{node.key}"',
                    )
                producer_by_product[product] = node

        for node in self.nodes:
            for product in node.requires:
                if product not in producer_by_product and product not in self.initial_products:
                    raise WorkflowValidationError(
                        ValidationErrorCode.DANGLING_REQUIRES,
                        f'node "{node.key}" requires dangling product "{product}"',
                    )

        required_products = {product for node in self.nodes for product in node.requires}
        for node in self.nodes:
            if not node.allow_failure:
                continue
            for product in node.provides:
                if product in required_products:
                    raise WorkflowValidationError(
                        ValidationErrorCode.ALLOW_FAILURE_PROVIDES_REQUIRED,
                        f'allow_failure node "{node.key}" provides required product "{product}"',
                    )

        try:
            topo_sort(self._adjacency(), {node.key for node in self.nodes})
        except ValueError as exc:
            raise WorkflowValidationError(
                ValidationErrorCode.CYCLE,
                "workflow dependency graph contains a cycle",
            ) from exc

    def edges(self) -> set[tuple[str, str]]:
        return {
            (source, target)
            for source, targets in self._adjacency().items()
            for target in targets
        }

    def topo_order(self) -> list[str]:
        return topo_sort(self._adjacency(), {node.key for node in self.nodes})

    def upstream_keys(self, node_key: str) -> set[str]:
        return {source for source, target in self.edges() if target == node_key}

    def _adjacency(self) -> dict[str, set[str]]:
        producer_by_product = {
            product: node.key for node in self.nodes for product in node.provides
        }
        adjacency = {node.key: set() for node in self.nodes}
        for node in self.nodes:
            for product in node.requires:
                producer = producer_by_product.get(product)
                if producer is not None:
                    adjacency[producer].add(node.key)
        return adjacency
