from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from uuid import uuid4

from market_cell.events import utc_now_iso
from market_cell.models import AnalysisRequest, CellManifest
from market_cell.registry import CellRegistry


CELL_EXECUTION_PLAN_SCHEMA_VERSION = "cell_execution_plan.v1"
CELL_RUNTIME_TRACE_SCHEMA_VERSION = "cell_runtime_trace.v1"

CellRuntime = Literal["python_local", "python_service", "rust_service", "external_service"]
ExecutionRole = Literal["leaf", "aggregator", "root"]
CpuWeight = Literal["unknown", "light", "medium", "heavy"]
LatencySensitivity = Literal["low", "normal", "high"]
RuntimeTraceStatus = Literal["succeeded", "failed", "skipped"]


@dataclass(frozen=True)
class ResourceHints:
    cpu_weight: CpuWeight = "unknown"
    latency_sensitivity: LatencySensitivity = "normal"
    stateful: bool = False
    expected_timeout_ms: int = 30_000
    max_retries: int = 0


@dataclass(frozen=True)
class CellServiceBinding:
    implementation_id: str
    cell_id: str
    service_id: str
    runtime: CellRuntime
    language: str
    formula_version: str
    endpoint: str | None = None
    task_queue: str | None = None
    priority: int = 100
    capabilities: list[str] = field(default_factory=list)
    supports_batch: bool = False
    max_concurrency: int | None = None
    resource_hints: ResourceHints = field(default_factory=ResourceHints)


@dataclass(frozen=True)
class CellExecutionNode:
    node_id: str
    cell_id: str
    formula_version: str
    execution_role: ExecutionRole
    dependencies: list[str] = field(default_factory=list)
    input_keys: list[str] = field(default_factory=list)
    output_keys: list[str] = field(default_factory=list)
    implementation_id: str | None = None
    resource_hints: ResourceHints = field(default_factory=ResourceHints)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CellExecutionPlan:
    plan_id: str
    target: str
    horizon: str
    root_node_id: str
    nodes: list[CellExecutionNode]
    service_bindings: list[CellServiceBinding]
    schema_version: str = CELL_EXECUTION_PLAN_SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_run_metadata(self) -> dict[str, Any]:
        return {"cell_execution_plan": self.to_dict()}


@dataclass(frozen=True)
class CellRuntimeTrace:
    trace_id: str
    span_id: str
    run_id: str
    node_id: str
    cell_id: str
    formula_version: str
    status: RuntimeTraceStatus
    started_at: str
    finished_at: str
    duration_ms: float
    schema_version: str = CELL_RUNTIME_TRACE_SCHEMA_VERSION
    plan_id: str | None = None
    implementation_id: str | None = None
    service_id: str | None = None
    runtime: CellRuntime | None = None
    retry_count: int = 0
    error: str | None = None
    parent_span_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_local_execution_plan(
    registry: CellRegistry,
    request: AnalysisRequest,
    service_id: str = "python-local",
) -> CellExecutionPlan:
    leaf_manifests = [cell.manifest() for cell in registry.leaf_cells]
    decision_manifest = registry.decision_cell.manifest()

    leaf_nodes = [
        _node_for_manifest(
            manifest,
            execution_role="leaf",
            dependencies=[],
            implementation_id=_implementation_id(service_id, manifest),
        )
        for manifest in leaf_manifests
    ]
    root_node = _node_for_manifest(
        decision_manifest,
        execution_role="root",
        dependencies=[node.node_id for node in leaf_nodes],
        implementation_id=_implementation_id(service_id, decision_manifest),
    )

    manifests = [*leaf_manifests, decision_manifest]
    return CellExecutionPlan(
        plan_id=uuid4().hex,
        target=request.target,
        horizon=request.horizon,
        root_node_id=root_node.node_id,
        nodes=[*leaf_nodes, root_node],
        service_bindings=[_local_binding(service_id, manifest) for manifest in manifests],
        metadata={
            "planner": "local_registry_static_v0.1",
            "cell_count": len(manifests),
        },
    )


def _node_for_manifest(
    manifest: CellManifest,
    execution_role: ExecutionRole,
    dependencies: list[str],
    implementation_id: str,
) -> CellExecutionNode:
    return CellExecutionNode(
        node_id=_node_id(manifest.cell_id),
        cell_id=manifest.cell_id,
        formula_version=manifest.formula_version,
        execution_role=execution_role,
        dependencies=dependencies,
        input_keys=list(manifest.inputs),
        output_keys=list(manifest.outputs),
        implementation_id=implementation_id,
    )


def _local_binding(service_id: str, manifest: CellManifest) -> CellServiceBinding:
    return CellServiceBinding(
        implementation_id=_implementation_id(service_id, manifest),
        cell_id=manifest.cell_id,
        service_id=service_id,
        runtime="python_local",
        language="python",
        formula_version=manifest.formula_version,
        task_queue="cell.python-local",
        capabilities=[manifest.category],
    )


def _node_id(cell_id: str) -> str:
    return f"cell:{cell_id}"


def _implementation_id(service_id: str, manifest: CellManifest) -> str:
    return f"{service_id}:{manifest.cell_id}:{manifest.formula_version}"
