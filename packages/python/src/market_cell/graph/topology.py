from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol, TypeVar


class DependencyNode(Protocol):
    node_id: str
    dependencies: list[str]


NodeT = TypeVar("NodeT", bound=DependencyNode)


def stable_topological_levels(
    node_by_id: Mapping[str, NodeT],
) -> tuple[list[list[str]], list[str]]:
    dependency_counts = {
        node_id: sum(1 for dependency in node.dependencies if dependency in node_by_id)
        for node_id, node in node_by_id.items()
    }
    dependents = {node_id: [] for node_id in node_by_id}
    for node in node_by_id.values():
        for dependency_id in node.dependencies:
            if dependency_id in dependents:
                dependents[dependency_id].append(node.node_id)

    current = sorted(node_id for node_id, count in dependency_counts.items() if count == 0)
    levels: list[list[str]] = []
    visited: set[str] = set()
    while current:
        levels.append(current)
        next_level: list[str] = []
        for node_id in current:
            visited.add(node_id)
            for dependent_id in sorted(dependents[node_id]):
                dependency_counts[dependent_id] -= 1
                if dependency_counts[dependent_id] == 0:
                    next_level.append(dependent_id)
        current = sorted(set(next_level))

    cyclic_nodes = sorted(set(node_by_id) - visited)
    return levels, cyclic_nodes


def dependency_closure(
    root_node_ids: Iterable[str],
    node_by_id: Mapping[str, NodeT],
) -> set[str]:
    reachable: set[str] = set()
    pending = list(root_node_ids)
    while pending:
        node_id = pending.pop()
        if node_id in reachable or node_id not in node_by_id:
            continue
        reachable.add(node_id)
        pending.extend(
            dependency_id
            for dependency_id in node_by_id[node_id].dependencies
            if dependency_id in node_by_id
        )
    return reachable
