from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from market_cell.graph.models import (
    CellGraphDefinition,
    CellGraphNode,
    CellOrganDefinition,
)
from market_cell.graph.topology import dependency_closure, stable_topological_levels
from market_cell.models import CellManifest


CELL_GRAPH_VALIDATION_SCHEMA_VERSION = "cell_graph_validation.v1"


GraphValidationCode = Literal[
    "duplicate_node_id",
    "missing_root",
    "invalid_root_role",
    "unexpected_root_role",
    "missing_dependency",
    "duplicate_dependency",
    "self_dependency",
    "leaf_has_dependencies",
    "cycle_detected",
    "unreachable_node",
    "missing_cell_implementation",
    "duplicate_organ_id",
    "duplicate_organ_node",
    "duplicate_organ_output",
    "organ_has_no_outputs",
    "missing_organ_node",
    "organ_output_not_member",
    "organ_dependency_outside_subgraph",
    "organ_unreachable_node",
]


@dataclass(frozen=True)
class GraphValidationIssue:
    code: GraphValidationCode
    message: str
    node_id: str | None = None
    dependency_id: str | None = None
    cell_id: str | None = None
    organ_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "node_id": self.node_id,
            "dependency_id": self.dependency_id,
            "cell_id": self.cell_id,
            "organ_id": self.organ_id,
        }


class CellGraphValidationError(ValueError):
    def __init__(
        self,
        graph: CellGraphDefinition,
        issues: list[GraphValidationIssue],
    ) -> None:
        self.graph = graph
        self.issues = list(issues)
        summary = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
        super().__init__(summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": "cell_graph_validation",
            "graph_id": self.graph.graph_id,
            "graph_version": self.graph.graph_version,
            "issues": [issue.to_dict() for issue in self.issues],
            "schema_version": CELL_GRAPH_VALIDATION_SCHEMA_VERSION,
        }


@dataclass(frozen=True)
class ValidatedCellGraphDefinition:
    graph: CellGraphDefinition
    topological_levels: list[list[str]]


def validate_cell_graph_definition(
    graph: CellGraphDefinition,
    manifests: Iterable[CellManifest] | None = None,
) -> ValidatedCellGraphDefinition:
    issues: list[GraphValidationIssue] = []
    node_by_id = _unique_nodes(graph, issues)
    _validate_root(graph, node_by_id, issues)
    _validate_nodes(graph, node_by_id, issues)
    if manifests is not None:
        _validate_cell_implementations(graph, manifests, issues)
    _validate_organs(graph, node_by_id, issues)

    topological_levels, cyclic_nodes = stable_topological_levels(node_by_id)
    if cyclic_nodes:
        issues.append(
            GraphValidationIssue(
                code="cycle_detected",
                message=f"cycle or cycle-blocked nodes: {', '.join(cyclic_nodes)}",
            )
        )
    _validate_reachability(graph, node_by_id, issues)

    if issues:
        raise CellGraphValidationError(graph, issues)
    return ValidatedCellGraphDefinition(
        graph=graph,
        topological_levels=topological_levels,
    )


def _unique_nodes(
    graph: CellGraphDefinition,
    issues: list[GraphValidationIssue],
) -> dict[str, CellGraphNode]:
    node_by_id: dict[str, CellGraphNode] = {}
    for node in graph.nodes:
        if node.node_id in node_by_id:
            issues.append(
                GraphValidationIssue(
                    code="duplicate_node_id",
                    message=f"node_id {node.node_id} appears more than once",
                    node_id=node.node_id,
                )
            )
            continue
        node_by_id[node.node_id] = node
    return node_by_id


def _validate_root(
    graph: CellGraphDefinition,
    node_by_id: dict[str, CellGraphNode],
    issues: list[GraphValidationIssue],
) -> None:
    root = node_by_id.get(graph.root_node_id)
    if root is None:
        issues.append(
            GraphValidationIssue(
                code="missing_root",
                message=f"root_node_id {graph.root_node_id} does not exist",
                node_id=graph.root_node_id,
            )
        )
    elif root.execution_role != "root":
        issues.append(
            GraphValidationIssue(
                code="invalid_root_role",
                message=f"root node {root.node_id} has role {root.execution_role}",
                node_id=root.node_id,
            )
        )
    for node in graph.nodes:
        if node.execution_role == "root" and node.node_id != graph.root_node_id:
            issues.append(
                GraphValidationIssue(
                    code="unexpected_root_role",
                    message=f"node {node.node_id} is root but is not root_node_id",
                    node_id=node.node_id,
                )
            )


def _validate_nodes(
    graph: CellGraphDefinition,
    node_by_id: dict[str, CellGraphNode],
    issues: list[GraphValidationIssue],
) -> None:
    for node in graph.nodes:
        if node.execution_role == "leaf" and node.dependencies:
            issues.append(
                GraphValidationIssue(
                    code="leaf_has_dependencies",
                    message=f"leaf node {node.node_id} has dependencies",
                    node_id=node.node_id,
                )
            )
        if len(node.dependencies) != len(set(node.dependencies)):
            issues.append(
                GraphValidationIssue(
                    code="duplicate_dependency",
                    message=f"node {node.node_id} repeats a dependency",
                    node_id=node.node_id,
                )
            )
        for dependency_id in node.dependencies:
            if dependency_id == node.node_id:
                issues.append(
                    GraphValidationIssue(
                        code="self_dependency",
                        message=f"node {node.node_id} depends on itself",
                        node_id=node.node_id,
                        dependency_id=dependency_id,
                    )
                )
            elif dependency_id not in node_by_id:
                issues.append(
                    GraphValidationIssue(
                        code="missing_dependency",
                        message=(
                            f"node {node.node_id} depends on missing node {dependency_id}"
                        ),
                        node_id=node.node_id,
                        dependency_id=dependency_id,
                    )
                )


def _validate_cell_implementations(
    graph: CellGraphDefinition,
    manifests: Iterable[CellManifest],
    issues: list[GraphValidationIssue],
) -> None:
    available_cell_ids = {manifest.cell_id for manifest in manifests}
    for node in graph.nodes:
        if node.cell_id not in available_cell_ids:
            issues.append(
                GraphValidationIssue(
                    code="missing_cell_implementation",
                    message=(
                        f"node {node.node_id} references unregistered Cell {node.cell_id}"
                    ),
                    node_id=node.node_id,
                    cell_id=node.cell_id,
                )
            )


def _validate_organs(
    graph: CellGraphDefinition,
    node_by_id: dict[str, CellGraphNode],
    issues: list[GraphValidationIssue],
) -> None:
    organ_ids: set[str] = set()
    for organ in graph.organs:
        if organ.organ_id in organ_ids:
            issues.append(
                GraphValidationIssue(
                    code="duplicate_organ_id",
                    message=f"organ_id {organ.organ_id} appears more than once",
                    organ_id=organ.organ_id,
                )
            )
        organ_ids.add(organ.organ_id)
        _validate_organ(organ, node_by_id, issues)


def _validate_organ(
    organ: CellOrganDefinition,
    node_by_id: dict[str, CellGraphNode],
    issues: list[GraphValidationIssue],
) -> None:
    member_ids = set(organ.node_ids)
    if len(member_ids) != len(organ.node_ids):
        issues.append(
            GraphValidationIssue(
                code="duplicate_organ_node",
                message=f"organ {organ.organ_id} repeats a node",
                organ_id=organ.organ_id,
            )
        )
    if len(set(organ.output_node_ids)) != len(organ.output_node_ids):
        issues.append(
            GraphValidationIssue(
                code="duplicate_organ_output",
                message=f"organ {organ.organ_id} repeats an output node",
                organ_id=organ.organ_id,
            )
        )
    if not organ.output_node_ids:
        issues.append(
            GraphValidationIssue(
                code="organ_has_no_outputs",
                message=f"organ {organ.organ_id} has no output nodes",
                organ_id=organ.organ_id,
            )
        )
    for node_id in organ.node_ids:
        if node_id not in node_by_id:
            issues.append(
                GraphValidationIssue(
                    code="missing_organ_node",
                    message=f"organ {organ.organ_id} references missing node {node_id}",
                    node_id=node_id,
                    organ_id=organ.organ_id,
                )
            )
    for output_node_id in organ.output_node_ids:
        if output_node_id not in member_ids:
            issues.append(
                GraphValidationIssue(
                    code="organ_output_not_member",
                    message=(
                        f"organ {organ.organ_id} output {output_node_id} is not a member"
                    ),
                    node_id=output_node_id,
                    organ_id=organ.organ_id,
                )
            )

    existing_members = {
        node_id: node_by_id[node_id]
        for node_id in member_ids
        if node_id in node_by_id
    }
    for node in existing_members.values():
        for dependency_id in node.dependencies:
            if dependency_id in node_by_id and dependency_id not in member_ids:
                issues.append(
                    GraphValidationIssue(
                        code="organ_dependency_outside_subgraph",
                        message=(
                            f"organ {organ.organ_id} node {node.node_id} depends on "
                            f"non-member {dependency_id}"
                        ),
                        node_id=node.node_id,
                        dependency_id=dependency_id,
                        organ_id=organ.organ_id,
                    )
                )

    valid_outputs = [
        node_id for node_id in organ.output_node_ids if node_id in existing_members
    ]
    if not valid_outputs:
        return
    reachable = dependency_closure(valid_outputs, existing_members)
    for node_id in sorted(set(existing_members) - reachable):
        issues.append(
            GraphValidationIssue(
                code="organ_unreachable_node",
                message=(
                    f"organ {organ.organ_id} node {node_id} is not reachable from outputs"
                ),
                node_id=node_id,
                organ_id=organ.organ_id,
            )
        )


def _validate_reachability(
    graph: CellGraphDefinition,
    node_by_id: dict[str, CellGraphNode],
    issues: list[GraphValidationIssue],
) -> None:
    if graph.root_node_id not in node_by_id:
        return
    reachable = dependency_closure([graph.root_node_id], node_by_id)
    for node_id in sorted(set(node_by_id) - reachable):
        issues.append(
            GraphValidationIssue(
                code="unreachable_node",
                message=(
                    f"node {node_id} is not reachable from root {graph.root_node_id}"
                ),
                node_id=node_id,
            )
        )
