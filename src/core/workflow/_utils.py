"""Workflow 内部图算法。"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping


def topo_sort(adjacency: Mapping[str, set[str]], nodes: set[str]) -> list[str]:
    """对有向图做拓扑排序；存在环时抛 ValueError。"""

    indegree = {node: 0 for node in nodes}
    for source, targets in adjacency.items():
        indegree.setdefault(source, 0)
        for target in targets:
            indegree[target] = indegree.get(target, 0) + 1

    queue = deque(sorted(node for node, degree in indegree.items() if degree == 0))
    ordered: list[str] = []

    while queue:
        node = queue.popleft()
        ordered.append(node)
        for target in sorted(adjacency.get(node, set())):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)

    if len(ordered) != len(indegree):
        raise ValueError("workflow dependency graph contains a cycle")
    return ordered
