from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from market_cell.execution.models import (
    CellExecutionNode,
    CellExecutionPlan,
    CellServiceBinding,
)


EXECUTION_PLAN_VALIDATION_SCHEMA_VERSION = "execution_plan_validation.v1"


PlanValidationCode = Literal[
    "duplicate_node_id",
    "duplicate_binding_id",
    "missing_root",
    "invalid_root_role",
    "unexpected_root_role",
    "missing_dependency",
    "duplicate_dependency",
    "self_dependency",
    "leaf_has_dependencies",
    "missing_binding",
    "binding_cell_mismatch",
    "binding_formula_mismatch",
    "unused_binding",
    "cycle_detected",
    "unreachable_node",
]


@dataclass(frozen=True)
class PlanValidationIssue:
    code: PlanValidationCode
    message: str
    node_id: str | None = None
    binding_id: str | None = None
    dependency_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "node_id": self.node_id,
            "binding_id": self.binding_id,
            "dependency_id": self.dependency_id,
        }


class ExecutionPlanValidationError(ValueError):
    def __init__(self, plan: CellExecutionPlan, issues: list[PlanValidationIssue]) -> None:
        self.plan = plan
        self.issues = list(issues)
        summary = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
        super().__init__(summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": "execution_plan_validation",
            "plan_id": self.plan.plan_id,
            "issues": [issue.to_dict() for issue in self.issues],
            "schema_version": EXECUTION_PLAN_VALIDATION_SCHEMA_VERSION,
        }


@dataclass(frozen=True)
class ValidatedExecutionPlan:
    plan: CellExecutionPlan
    topological_levels: list[list[str]]


def validate_execution_plan(plan: CellExecutionPlan) -> ValidatedExecutionPlan:
    issues: list[PlanValidationIssue] = []
    node_by_id = _unique_nodes(plan, issues)
    binding_by_id = _unique_bindings(plan, issues)
    _validate_root(plan, node_by_id, issues)
    _validate_nodes(plan, node_by_id, binding_by_id, issues)
    _validate_binding_usage(plan, issues)

    topological_levels, cyclic_nodes = _topological_levels(node_by_id)
    if cyclic_nodes:
        issues.append(
            PlanValidationIssue(
                code="cycle_detected",
                message=f"cycle or cycle-blocked nodes: {', '.join(cyclic_nodes)}",
            )
        )
    _validate_reachability(plan, node_by_id, issues)

    if issues:
        raise ExecutionPlanValidationError(plan, issues)
    return ValidatedExecutionPlan(plan=plan, topological_levels=topological_levels)


def _unique_nodes(
    plan: CellExecutionPlan,
    issues: list[PlanValidationIssue],
) -> dict[str, CellExecutionNode]:
    node_by_id: dict[str, CellExecutionNode] = {}
    for node in plan.nodes:
        if node.node_id in node_by_id:
            issues.append(
                PlanValidationIssue(
                    code="duplicate_node_id",
                    message=f"node_id {node.node_id} appears more than once",
                    node_id=node.node_id,
                )
            )
            continue
        node_by_id[node.node_id] = node
    return node_by_id


def _unique_bindings(
    plan: CellExecutionPlan,
    issues: list[PlanValidationIssue],
) -> dict[str, CellServiceBinding]:
    binding_by_id: dict[str, CellServiceBinding] = {}
    for binding in plan.service_bindings:
        if binding.binding_id in binding_by_id:
            issues.append(
                PlanValidationIssue(
                    code="duplicate_binding_id",
                    message=f"binding_id {binding.binding_id} appears more than once",
                    binding_id=binding.binding_id,
                )
            )
            continue
        binding_by_id[binding.binding_id] = binding
    return binding_by_id


def _validate_root(
    plan: CellExecutionPlan,
    node_by_id: dict[str, CellExecutionNode],
    issues: list[PlanValidationIssue],
) -> None:
    root = node_by_id.get(plan.root_node_id)
    if root is None:
        issues.append(
            PlanValidationIssue(
                code="missing_root",
                message=f"root_node_id {plan.root_node_id} does not exist",
                node_id=plan.root_node_id,
            )
        )
    elif root.execution_role != "root":
        issues.append(
            PlanValidationIssue(
                code="invalid_root_role",
                message=f"root node {root.node_id} has role {root.execution_role}",
                node_id=root.node_id,
            )
        )
    for node in plan.nodes:
        if node.execution_role == "root" and node.node_id != plan.root_node_id:
            issues.append(
                PlanValidationIssue(
                    code="unexpected_root_role",
                    message=f"node {node.node_id} is root but is not root_node_id",
                    node_id=node.node_id,
                )
            )


def _validate_nodes(
    plan: CellExecutionPlan,
    node_by_id: dict[str, CellExecutionNode],
    binding_by_id: dict[str, CellServiceBinding],
    issues: list[PlanValidationIssue],
) -> None:
    for node in plan.nodes:
        if node.execution_role == "leaf" and node.dependencies:
            issues.append(
                PlanValidationIssue(
                    code="leaf_has_dependencies",
                    message=f"leaf node {node.node_id} has dependencies",
                    node_id=node.node_id,
                )
            )
        if len(node.dependencies) != len(set(node.dependencies)):
            issues.append(
                PlanValidationIssue(
                    code="duplicate_dependency",
                    message=f"node {node.node_id} repeats a dependency",
                    node_id=node.node_id,
                )
            )
        for dependency_id in node.dependencies:
            if dependency_id == node.node_id:
                issues.append(
                    PlanValidationIssue(
                        code="self_dependency",
                        message=f"node {node.node_id} depends on itself",
                        node_id=node.node_id,
                        dependency_id=dependency_id,
                    )
                )
            elif dependency_id not in node_by_id:
                issues.append(
                    PlanValidationIssue(
                        code="missing_dependency",
                        message=f"node {node.node_id} depends on missing node {dependency_id}",
                        node_id=node.node_id,
                        dependency_id=dependency_id,
                    )
                )

        binding = binding_by_id.get(node.binding_id)
        if binding is None:
            issues.append(
                PlanValidationIssue(
                    code="missing_binding",
                    message=f"node {node.node_id} references missing binding {node.binding_id}",
                    node_id=node.node_id,
                    binding_id=node.binding_id,
                )
            )
            continue
        if node.cell_id != binding.cell_id:
            issues.append(_binding_issue("binding_cell_mismatch", node, binding))
        if node.formula_version != binding.formula_version:
            issues.append(_binding_issue("binding_formula_mismatch", node, binding))


def _binding_issue(
    code: PlanValidationCode,
    node: CellExecutionNode,
    binding: CellServiceBinding,
) -> PlanValidationIssue:
    return PlanValidationIssue(
        code=code,
        message=f"node {node.node_id} is incompatible with binding {binding.binding_id}",
        node_id=node.node_id,
        binding_id=binding.binding_id,
    )


def _validate_binding_usage(
    plan: CellExecutionPlan,
    issues: list[PlanValidationIssue],
) -> None:
    used_binding_ids = {node.binding_id for node in plan.nodes}
    for binding in plan.service_bindings:
        if binding.binding_id not in used_binding_ids:
            issues.append(
                PlanValidationIssue(
                    code="unused_binding",
                    message=f"binding {binding.binding_id} is not used by any node",
                    binding_id=binding.binding_id,
                )
            )


def _topological_levels(
    node_by_id: dict[str, CellExecutionNode],
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


def _validate_reachability(
    plan: CellExecutionPlan,
    node_by_id: dict[str, CellExecutionNode],
    issues: list[PlanValidationIssue],
) -> None:
    if plan.root_node_id not in node_by_id:
        return
    reachable: set[str] = set()
    pending = [plan.root_node_id]
    while pending:
        node_id = pending.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        pending.extend(
            dependency_id
            for dependency_id in node_by_id[node_id].dependencies
            if dependency_id in node_by_id
        )
    for node_id in sorted(set(node_by_id) - reachable):
        issues.append(
            PlanValidationIssue(
                code="unreachable_node",
                message=f"node {node_id} is not reachable from root {plan.root_node_id}",
                node_id=node_id,
            )
        )
