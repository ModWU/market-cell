from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from market_cell.execution.models import (
    CellExecutionNode,
    CellExecutionPlan,
    CellServiceBinding,
)
from market_cell.graph.topology import dependency_closure, stable_topological_levels
from market_cell.inputs import InputKind, InputReference


EXECUTION_PLAN_VALIDATION_SCHEMA_VERSION = "execution_plan_validation.v1"


PlanValidationCode = Literal[
    "duplicate_node_id",
    "duplicate_binding_id",
    "duplicate_input_reference_id",
    "input_reference_scope_mismatch",
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
    "duplicate_fallback_binding",
    "primary_binding_in_fallback",
    "missing_fallback_binding",
    "fallback_binding_cell_mismatch",
    "fallback_binding_formula_mismatch",
    "unused_binding",
    "missing_node_input_reference",
    "duplicate_node_input_reference",
    "missing_input_reference",
    "duplicate_required_input_kind",
    "missing_required_input_kind",
    "unexpected_input_kind",
    "unused_input_reference",
    "cycle_detected",
    "unreachable_node",
]


@dataclass(frozen=True)
class PlanValidationIssue:
    code: PlanValidationCode
    message: str
    node_id: str | None = None
    binding_id: str | None = None
    reference_id: str | None = None
    dependency_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "node_id": self.node_id,
            "binding_id": self.binding_id,
            "reference_id": self.reference_id,
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
    reference_by_id = _unique_input_references(plan, issues)
    _validate_input_reference_scope(plan, issues)
    _validate_root(plan, node_by_id, issues)
    _validate_nodes(plan, node_by_id, binding_by_id, reference_by_id, issues)
    _validate_binding_usage(plan, issues)
    _validate_input_reference_usage(plan, issues)

    topological_levels, cyclic_nodes = stable_topological_levels(node_by_id)
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


def _unique_input_references(
    plan: CellExecutionPlan,
    issues: list[PlanValidationIssue],
) -> dict[str, InputReference]:
    reference_by_id: dict[str, InputReference] = {}
    for reference in plan.input_references:
        if reference.reference_id in reference_by_id:
            issues.append(
                PlanValidationIssue(
                    code="duplicate_input_reference_id",
                    message=(
                        f"input reference {reference.reference_id} appears more than once"
                    ),
                    reference_id=reference.reference_id,
                )
            )
            continue
        reference_by_id[reference.reference_id] = reference
    return reference_by_id


def _validate_input_reference_scope(
    plan: CellExecutionPlan,
    issues: list[PlanValidationIssue],
) -> None:
    for reference in plan.input_references:
        if reference.target == plan.target and reference.horizon == plan.horizon:
            continue
        issues.append(
            PlanValidationIssue(
                code="input_reference_scope_mismatch",
                message=(
                    f"input reference {reference.reference_id} has scope "
                    f"{reference.target}/{reference.horizon}, expected "
                    f"{plan.target}/{plan.horizon}"
                ),
                reference_id=reference.reference_id,
            )
        )


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
    reference_by_id: dict[str, InputReference],
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
        if not node.input_reference_ids:
            issues.append(
                PlanValidationIssue(
                    code="missing_node_input_reference",
                    message=f"node {node.node_id} has no input reference",
                    node_id=node.node_id,
                )
            )
        if len(node.input_reference_ids) != len(set(node.input_reference_ids)):
            issues.append(
                PlanValidationIssue(
                    code="duplicate_node_input_reference",
                    message=f"node {node.node_id} repeats an input reference",
                    node_id=node.node_id,
                )
            )
        for reference_id in node.input_reference_ids:
            if reference_id not in reference_by_id:
                issues.append(
                    PlanValidationIssue(
                        code="missing_input_reference",
                        message=(
                            f"node {node.node_id} references missing input {reference_id}"
                        ),
                        node_id=node.node_id,
                        reference_id=reference_id,
                    )
                )
        _validate_node_input_kinds(node, reference_by_id, issues)
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

        if len(node.fallback_binding_ids) != len(set(node.fallback_binding_ids)):
            issues.append(
                PlanValidationIssue(
                    code="duplicate_fallback_binding",
                    message=f"node {node.node_id} repeats a fallback binding",
                    node_id=node.node_id,
                )
            )
        if node.binding_id in node.fallback_binding_ids:
            issues.append(
                PlanValidationIssue(
                    code="primary_binding_in_fallback",
                    message=(
                        f"node {node.node_id} repeats primary binding "
                        f"{node.binding_id} as fallback"
                    ),
                    node_id=node.node_id,
                    binding_id=node.binding_id,
                )
            )
        _validate_node_binding(
            node=node,
            binding_id=node.binding_id,
            binding_by_id=binding_by_id,
            issues=issues,
            fallback=False,
        )
        for fallback_binding_id in node.fallback_binding_ids:
            _validate_node_binding(
                node=node,
                binding_id=fallback_binding_id,
                binding_by_id=binding_by_id,
                issues=issues,
                fallback=True,
            )


def _validate_node_input_kinds(
    node: CellExecutionNode,
    reference_by_id: dict[str, InputReference],
    issues: list[PlanValidationIssue],
) -> None:
    required_kinds = list(node.required_input_kinds)
    if len(required_kinds) != len(set(required_kinds)):
        issues.append(
            PlanValidationIssue(
                code="duplicate_required_input_kind",
                message=f"node {node.node_id} repeats a required input kind",
                node_id=node.node_id,
            )
        )

    referenced_kinds: list[InputKind] = [
        reference_by_id[reference_id].input_kind
        for reference_id in node.input_reference_ids
        if reference_id in reference_by_id
    ]
    required_kind_set = set(required_kinds)
    referenced_kind_set = set(referenced_kinds)
    if "analysis_request" not in required_kind_set:
        issues.append(
            PlanValidationIssue(
                code="missing_required_input_kind",
                message=(
                    f"node {node.node_id} must declare analysis_request as a "
                    "required input kind"
                ),
                node_id=node.node_id,
            )
        )
    for input_kind in sorted(required_kind_set - referenced_kind_set):
        issues.append(
            PlanValidationIssue(
                code="missing_required_input_kind",
                message=(
                    f"node {node.node_id} is missing required input kind {input_kind}"
                ),
                node_id=node.node_id,
            )
        )
    for input_kind in sorted(referenced_kind_set - required_kind_set):
        reference = next(
            reference_by_id[reference_id]
            for reference_id in node.input_reference_ids
            if reference_id in reference_by_id
            and reference_by_id[reference_id].input_kind == input_kind
        )
        issues.append(
            PlanValidationIssue(
                code="unexpected_input_kind",
                message=(
                    f"node {node.node_id} references undeclared input kind {input_kind}"
                ),
                node_id=node.node_id,
                reference_id=reference.reference_id,
            )
        )

    for input_kind in sorted(referenced_kind_set):
        matching_references = [
            reference_by_id[reference_id]
            for reference_id in node.input_reference_ids
            if reference_id in reference_by_id
            and reference_by_id[reference_id].input_kind == input_kind
        ]
        if len(matching_references) <= 1:
            continue
        issues.append(
            PlanValidationIssue(
                code="unexpected_input_kind",
                message=(
                    f"node {node.node_id} references input kind {input_kind} more than once"
                ),
                node_id=node.node_id,
                reference_id=matching_references[1].reference_id,
            )
        )

    if (
        len(required_kinds) == len(set(required_kinds))
        and len(referenced_kinds) == len(set(referenced_kinds))
        and required_kind_set == referenced_kind_set
        and required_kinds != referenced_kinds
    ):
        mismatch_index = next(
            index
            for index, (required, actual) in enumerate(
                zip(required_kinds, referenced_kinds, strict=True)
            )
            if required != actual
        )
        reference_id = node.input_reference_ids[mismatch_index]
        issues.append(
            PlanValidationIssue(
                code="unexpected_input_kind",
                message=(
                    f"node {node.node_id} input kind order does not match its "
                    "required input declaration"
                ),
                node_id=node.node_id,
                reference_id=reference_id,
            )
        )


def _validate_node_binding(
    *,
    node: CellExecutionNode,
    binding_id: str,
    binding_by_id: dict[str, CellServiceBinding],
    issues: list[PlanValidationIssue],
    fallback: bool,
) -> None:
    binding = binding_by_id.get(binding_id)
    if binding is None:
        issues.append(
            PlanValidationIssue(
                code="missing_fallback_binding" if fallback else "missing_binding",
                message=(
                    f"node {node.node_id} references missing "
                    f"{'fallback ' if fallback else ''}binding {binding_id}"
                ),
                node_id=node.node_id,
                binding_id=binding_id,
            )
        )
        return
    if node.cell_id != binding.cell_id:
        issues.append(
            _binding_issue(
                "fallback_binding_cell_mismatch" if fallback else "binding_cell_mismatch",
                node,
                binding,
            )
        )
    if node.formula_version != binding.formula_version:
        issues.append(
            _binding_issue(
                (
                    "fallback_binding_formula_mismatch"
                    if fallback
                    else "binding_formula_mismatch"
                ),
                node,
                binding,
            )
        )


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
    used_binding_ids = {
        binding_id
        for node in plan.nodes
        for binding_id in [node.binding_id, *node.fallback_binding_ids]
    }
    for binding in plan.service_bindings:
        if binding.binding_id not in used_binding_ids:
            issues.append(
                PlanValidationIssue(
                    code="unused_binding",
                    message=f"binding {binding.binding_id} is not used by any node",
                    binding_id=binding.binding_id,
                )
            )


def _validate_input_reference_usage(
    plan: CellExecutionPlan,
    issues: list[PlanValidationIssue],
) -> None:
    used_reference_ids = {
        reference_id
        for node in plan.nodes
        for reference_id in node.input_reference_ids
    }
    for reference in plan.input_references:
        if reference.reference_id not in used_reference_ids:
            issues.append(
                PlanValidationIssue(
                    code="unused_input_reference",
                    message=(
                        f"input reference {reference.reference_id} is not used by any node"
                    ),
                    reference_id=reference.reference_id,
                )
            )


def _validate_reachability(
    plan: CellExecutionPlan,
    node_by_id: dict[str, CellExecutionNode],
    issues: list[PlanValidationIssue],
) -> None:
    if plan.root_node_id not in node_by_id:
        return
    reachable = dependency_closure([plan.root_node_id], node_by_id)
    for node_id in sorted(set(node_by_id) - reachable):
        issues.append(
            PlanValidationIssue(
                code="unreachable_node",
                message=f"node {node_id} is not reachable from root {plan.root_node_id}",
                node_id=node_id,
            )
        )
