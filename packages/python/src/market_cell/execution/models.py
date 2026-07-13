from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from market_cell.events import utc_now_iso


CELL_EXECUTION_PLAN_SCHEMA_VERSION = "cell_execution_plan.v2"
CELL_RUNTIME_TRACE_SCHEMA_VERSION = "cell_runtime_trace.v1"
CELL_RUNTIME_SUMMARY_SCHEMA_VERSION = "cell_runtime_summary.v1"

CellRuntime = Literal["python_local", "python_service", "rust_service", "external_service"]
ExecutionRole = Literal["leaf", "aggregator", "root"]
CpuWeight = Literal["unknown", "light", "medium", "heavy"]
LatencySensitivity = Literal["low", "normal", "high"]
RuntimeTraceStatus = Literal["succeeded", "failed", "skipped"]


def service_binding_id(implementation_id: str, service_id: str) -> str:
    return f"binding:{service_id}:{implementation_id}"


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
    binding_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "binding_id",
            service_binding_id(self.implementation_id, self.service_id),
        )


@dataclass(frozen=True)
class CellExecutionNode:
    node_id: str
    cell_id: str
    formula_version: str
    execution_role: ExecutionRole
    binding_id: str
    dependencies: list[str] = field(default_factory=list)
    input_keys: list[str] = field(default_factory=list)
    output_keys: list[str] = field(default_factory=list)
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


@dataclass(frozen=True)
class CellRuntimeSummary:
    cell_id: str
    formula_version: str
    implementation_id: str | None
    service_id: str | None
    runtime: CellRuntime | None
    trace_count: int
    succeeded_count: int
    failed_count: int
    skipped_count: int
    average_duration_ms: float
    max_duration_ms: float
    min_duration_ms: float
    p95_duration_ms: float
    error_count: int
    retry_count: int
    schema_version: str = CELL_RUNTIME_SUMMARY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
