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
)
from market_cell.execution.placement import (
    CellPlacementDecision,
    CellPlacementPolicy,
    RuntimeAwarePlacementPolicy,
)
from market_cell.execution.plan_validation import validate_execution_plan
from market_cell.graph import (
    CellGraphDefinition,
    CellGraphNode,
    default_analysis_graph,
    validate_cell_graph_definition,
)
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
        graph_definition: CellGraphDefinition | None = None,
    ) -> CellExecutionPlan:
        graph = graph_definition or default_analysis_graph()
        registry_manifests = registry.manifests()
        validate_cell_graph_definition(graph, registry_manifests)
        manifest_by_cell = {
            manifest.cell_id: manifest for manifest in registry_manifests
        }
        graph_cell_ids = list(dict.fromkeys(node.cell_id for node in graph.nodes))
        manifests = [manifest_by_cell[cell_id] for cell_id in graph_cell_ids]
        decisions = [self._place(manifest) for manifest in manifests]
        decision_by_cell = {decision.cell_id: decision for decision in decisions}

        nodes = [
            _node_for_graph_node(
                graph_node,
                manifest_by_cell[graph_node.cell_id],
                decision_by_cell[graph_node.cell_id].selected_binding.binding_id,
            )
            for graph_node in graph.nodes
        ]

        plan = CellExecutionPlan(
            plan_id=uuid4().hex,
            target=request.target,
            horizon=request.horizon,
            root_node_id=graph.root_node_id,
            nodes=nodes,
            service_bindings=[
                decision_by_cell[manifest.cell_id].selected_binding
                for manifest in manifests
            ],
            metadata={
                "planner": "cell_graph_service_placement_v0.3",
                "catalog_id": self.catalog.catalog_id,
                "catalog_schema_version": self.catalog.schema_version,
                "graph_id": graph.graph_id,
                "graph_version": graph.graph_version,
                "graph_schema_version": graph.schema_version,
                "organs": [
                    {
                        "organ_id": organ.organ_id,
                        "organ_version": organ.organ_version,
                    }
                    for organ in graph.organs
                ],
                "placement_policy": self.placement_policy.name,
                "placement_decisions": [decision.to_dict() for decision in decisions],
                "candidate_binding_count": len(self.catalog.bindings),
                "cell_count": len(manifests),
                "node_count": len(graph.nodes),
                "organ_count": len(graph.organs),
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
    graph_definition: CellGraphDefinition | None = None,
    placement_policy: CellPlacementPolicy | None = None,
    runtime_summaries: list[CellRuntimeSummary] | None = None,
) -> CellExecutionPlan:
    return CellExecutionPlanner(
        catalog,
        placement_policy=placement_policy,
        runtime_summaries=runtime_summaries,
    ).build(registry, request, graph_definition)


def build_local_execution_plan(
    registry: CellRegistry,
    request: AnalysisRequest,
    service_id: str = "python-local",
    *,
    graph_definition: CellGraphDefinition | None = None,
) -> CellExecutionPlan:
    catalog = build_local_capability_catalog(registry, service_id)
    return build_execution_plan(
        registry,
        request,
        catalog,
        graph_definition=graph_definition,
    )


def _node_for_graph_node(
    graph_node: CellGraphNode,
    manifest: CellManifest,
    binding_id: str,
) -> CellExecutionNode:
    return CellExecutionNode(
        node_id=graph_node.node_id,
        cell_id=manifest.cell_id,
        formula_version=manifest.formula_version,
        execution_role=graph_node.execution_role,
        binding_id=binding_id,
        dependencies=list(graph_node.dependencies),
        input_keys=list(manifest.inputs),
        output_keys=list(manifest.outputs),
        metadata=dict(graph_node.metadata),
    )
