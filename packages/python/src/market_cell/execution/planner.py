from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from market_cell.execution.catalog import (
    ServiceCapabilityCatalog,
    build_local_capability_catalog,
)
from market_cell.execution.models import (
    CellExecutionNode,
    CellExecutionPlan,
    CellRuntimeSummary,
    ExecutionRole,
)
from market_cell.execution.placement import (
    CellPlacementDecision,
    CellPlacementPolicy,
    RuntimeAwarePlacementPolicy,
)
from market_cell.execution.plan_validation import validate_execution_plan
from market_cell.models import AnalysisRequest, CellManifest
from market_cell.registry import CellRegistry


class CellExecutionPlanner:
    def __init__(
        self,
        catalog: ServiceCapabilityCatalog,
        *,
        placement_policy: CellPlacementPolicy | None = None,
        runtime_summaries: list[CellRuntimeSummary] | None = None,
    ) -> None:
        self.catalog = catalog
        self.placement_policy = placement_policy or RuntimeAwarePlacementPolicy()
        self.runtime_summaries = list(runtime_summaries or [])

    def build(
        self,
        registry: CellRegistry,
        request: AnalysisRequest,
    ) -> CellExecutionPlan:
        leaf_manifests = [cell.manifest() for cell in registry.leaf_cells]
        decision_manifest = registry.decision_cell.manifest()
        manifests = [*leaf_manifests, decision_manifest]
        decisions = [self._place(manifest) for manifest in manifests]
        decision_by_cell = {decision.cell_id: decision for decision in decisions}

        leaf_nodes = [
            _node_for_manifest(
                manifest,
                execution_role="leaf",
                dependencies=[],
                binding_id=decision_by_cell[manifest.cell_id].selected_binding.binding_id,
            )
            for manifest in leaf_manifests
        ]
        root_node = _node_for_manifest(
            decision_manifest,
            execution_role="root",
            dependencies=[node.node_id for node in leaf_nodes],
            binding_id=decision_by_cell[decision_manifest.cell_id].selected_binding.binding_id,
        )

        plan = CellExecutionPlan(
            plan_id=uuid4().hex,
            target=request.target,
            horizon=request.horizon,
            root_node_id=root_node.node_id,
            nodes=[*leaf_nodes, root_node],
            service_bindings=[
                decision_by_cell[manifest.cell_id].selected_binding
                for manifest in manifests
            ],
            metadata={
                "planner": "service_capability_catalog_v0.2",
                "catalog_id": self.catalog.catalog_id,
                "catalog_schema_version": self.catalog.schema_version,
                "placement_policy": self.placement_policy.name,
                "placement_decisions": [decision.to_dict() for decision in decisions],
                "candidate_binding_count": len(self.catalog.bindings),
                "cell_count": len(manifests),
            },
        )
        validated = validate_execution_plan(plan)
        return replace(
            plan,
            metadata={
                **plan.metadata,
                "topological_levels": validated.topological_levels,
            },
        )

    def _place(self, manifest: CellManifest) -> CellPlacementDecision:
        return self.placement_policy.select(
            manifest,
            self.catalog.candidates_for(manifest),
            self.runtime_summaries,
        )


def build_execution_plan(
    registry: CellRegistry,
    request: AnalysisRequest,
    catalog: ServiceCapabilityCatalog,
    *,
    placement_policy: CellPlacementPolicy | None = None,
    runtime_summaries: list[CellRuntimeSummary] | None = None,
) -> CellExecutionPlan:
    return CellExecutionPlanner(
        catalog,
        placement_policy=placement_policy,
        runtime_summaries=runtime_summaries,
    ).build(registry, request)


def build_local_execution_plan(
    registry: CellRegistry,
    request: AnalysisRequest,
    service_id: str = "python-local",
) -> CellExecutionPlan:
    catalog = build_local_capability_catalog(registry, service_id)
    return build_execution_plan(registry, request, catalog)


def _node_for_manifest(
    manifest: CellManifest,
    execution_role: ExecutionRole,
    dependencies: list[str],
    binding_id: str,
) -> CellExecutionNode:
    return CellExecutionNode(
        node_id=f"cell:{manifest.cell_id}",
        cell_id=manifest.cell_id,
        formula_version=manifest.formula_version,
        execution_role=execution_role,
        binding_id=binding_id,
        dependencies=dependencies,
        input_keys=list(manifest.inputs),
        output_keys=list(manifest.outputs),
    )
