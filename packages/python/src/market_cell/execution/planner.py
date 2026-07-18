from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import get_args
from uuid import uuid4

from market_cell.execution.catalog import (
    ServiceCapabilityCatalog,
    build_local_capability_catalog,
)
from market_cell.execution.models import (
    CellExecutionNode,
    CellExecutionPlan,
    CellServiceBinding,
    ResourceHints,
)
from market_cell.execution.placement import (
    CellPlacementDecision,
    CellPlacementPolicy,
    PlacementUnavailableError,
    RuntimeAwarePlacementPolicy,
)
from market_cell.execution.plan_validation import validate_execution_plan
from market_cell.execution.runtime_store import RuntimeSummarySnapshot
from market_cell.graph import (
    CellGraphDefinition,
    CellGraphNode,
    default_analysis_graph,
    validate_cell_graph_definition,
)
from market_cell.inputs import (
    InputCompositionError,
    InputKind,
    InputReference,
    InputSnapshot,
)
from market_cell.models import AnalysisRequest, CellManifest
from market_cell.registry import CellRegistry


class CellExecutionPlanner:
    def __init__(
        self,
        catalog: ServiceCapabilityCatalog,
        *,
        placement_policy: CellPlacementPolicy | None = None,
        runtime_summary_snapshot: RuntimeSummarySnapshot | None = None,
    ) -> None:
        self.catalog = catalog
        self.placement_policy = placement_policy or RuntimeAwarePlacementPolicy()
        self.runtime_summary_snapshot = (
            runtime_summary_snapshot
            or RuntimeSummarySnapshot.empty(window=timedelta(days=30))
        )

    def build(
        self,
        registry: CellRegistry,
        request: AnalysisRequest,
        graph_definition: CellGraphDefinition | None = None,
        input_references: list[InputReference] | None = None,
    ) -> CellExecutionPlan:
        graph = graph_definition or default_analysis_graph()
        references = list(
            input_references
            or [InputSnapshot.from_analysis_request(request).to_reference()]
        )
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
                [
                    binding.binding_id
                    for binding in decision_by_cell[
                        graph_node.cell_id
                    ].fallback_bindings
                ],
                decision_by_cell[graph_node.cell_id].selected_binding.resource_hints,
                _references_for_manifest(
                    manifest_by_cell[graph_node.cell_id],
                    references,
                ),
            )
            for graph_node in graph.nodes
        ]

        plan = CellExecutionPlan(
            plan_id=uuid4().hex,
            target=request.target,
            horizon=request.horizon,
            root_node_id=graph.root_node_id,
            nodes=nodes,
            input_references=references,
            service_bindings=_plan_bindings(decisions),
            metadata={
                "planner": "cell_graph_service_placement_v0.7",
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
                "runtime_summary_snapshot": self.runtime_summary_snapshot.to_dict(),
                "placement_decisions": [decision.to_dict() for decision in decisions],
                "candidate_binding_count": len(self.catalog.bindings),
                "cell_count": len(manifests),
                "node_count": len(graph.nodes),
                "organ_count": len(graph.organs),
                "input_reference_count": len(references),
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
        candidates = self.catalog.candidates_for(manifest)
        decision = self.placement_policy.select(
            manifest,
            candidates,
            self.runtime_summary_snapshot,
        )
        candidate_by_id = {binding.binding_id: binding for binding in candidates}
        decision_bindings = [
            decision.selected_binding,
            *decision.fallback_bindings,
        ]
        decision_binding_ids = [binding.binding_id for binding in decision_bindings]
        if (
            decision.cell_id != manifest.cell_id
            or decision.formula_version != manifest.formula_version
            or len(decision_binding_ids) != len(set(decision_binding_ids))
            or any(
                candidate_by_id.get(binding.binding_id) != binding
                for binding in decision_bindings
            )
        ):
            raise PlacementUnavailableError(
                f"placement policy {self.placement_policy.name} returned an invalid "
                f"binding decision for {manifest.cell_id}@{manifest.formula_version}"
            )
        return decision


def build_execution_plan(
    registry: CellRegistry,
    request: AnalysisRequest,
    catalog: ServiceCapabilityCatalog,
    *,
    graph_definition: CellGraphDefinition | None = None,
    input_references: list[InputReference] | None = None,
    placement_policy: CellPlacementPolicy | None = None,
    runtime_summary_snapshot: RuntimeSummarySnapshot | None = None,
) -> CellExecutionPlan:
    return CellExecutionPlanner(
        catalog,
        placement_policy=placement_policy,
        runtime_summary_snapshot=runtime_summary_snapshot,
    ).build(registry, request, graph_definition, input_references)


def build_local_execution_plan(
    registry: CellRegistry,
    request: AnalysisRequest,
    service_id: str = "python-local",
    *,
    graph_definition: CellGraphDefinition | None = None,
    input_references: list[InputReference] | None = None,
    runtime_summary_snapshot: RuntimeSummarySnapshot | None = None,
) -> CellExecutionPlan:
    catalog = build_local_capability_catalog(registry, service_id)
    return build_execution_plan(
        registry,
        request,
        catalog,
        graph_definition=graph_definition,
        input_references=input_references,
        runtime_summary_snapshot=runtime_summary_snapshot,
    )


def _node_for_graph_node(
    graph_node: CellGraphNode,
    manifest: CellManifest,
    binding_id: str,
    fallback_binding_ids: list[str],
    resource_hints: ResourceHints,
    input_references: list[InputReference],
) -> CellExecutionNode:
    return CellExecutionNode(
        node_id=graph_node.node_id,
        cell_id=manifest.cell_id,
        formula_version=manifest.formula_version,
        execution_role=graph_node.execution_role,
        binding_id=binding_id,
        fallback_binding_ids=list(fallback_binding_ids),
        dependencies=list(graph_node.dependencies),
        input_reference_ids=[
            reference.reference_id for reference in input_references
        ],
        required_input_kinds=list(manifest.required_input_kinds),
        input_keys=list(manifest.inputs),
        output_keys=list(manifest.outputs),
        resource_hints=resource_hints,
        metadata=dict(graph_node.metadata),
    )


def _references_for_manifest(
    manifest: CellManifest,
    references: list[InputReference],
) -> list[InputReference]:
    required_kinds = list(manifest.required_input_kinds)
    if len(required_kinds) != len(set(required_kinds)):
        raise InputCompositionError(
            f"Cell {manifest.cell_id} repeats a required input kind"
        )
    if "analysis_request" not in required_kinds:
        raise InputCompositionError(
            f"Cell {manifest.cell_id} must require analysis_request"
        )
    supported_kinds = set(get_args(InputKind))
    unsupported = sorted(set(required_kinds) - supported_kinds)
    if unsupported:
        raise InputCompositionError(
            f"Cell {manifest.cell_id} requires unsupported input kinds: "
            + ", ".join(unsupported)
        )
    references_by_kind = {
        input_kind: [
            reference
            for reference in references
            if reference.input_kind == input_kind
        ]
        for input_kind in required_kinds
    }
    missing = sorted(
        input_kind
        for input_kind, matches in references_by_kind.items()
        if not matches
    )
    if missing:
        raise InputCompositionError(
            f"Cell {manifest.cell_id} is missing required input kinds: "
            + ", ".join(missing)
        )
    # Repeated kinds need named slots/cardinality semantics; silently choosing
    # one would make cross-language plans ambiguous.
    duplicate_kinds = sorted(
        input_kind
        for input_kind, matches in references_by_kind.items()
        if len(matches) > 1
    )
    if duplicate_kinds:
        raise InputCompositionError(
            f"Cell {manifest.cell_id} received multiple snapshots for input kinds: "
            + ", ".join(duplicate_kinds)
        )
    return [references_by_kind[input_kind][0] for input_kind in required_kinds]


def _plan_bindings(
    decisions: list[CellPlacementDecision],
) -> list[CellServiceBinding]:
    bindings: list[CellServiceBinding] = []
    seen_binding_ids: set[str] = set()
    for decision in decisions:
        for binding in [decision.selected_binding, *decision.fallback_bindings]:
            if binding.binding_id in seen_binding_ids:
                continue
            bindings.append(binding)
            seen_binding_ids.add(binding.binding_id)
    return bindings
