from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from market_cell.events import utc_now_iso
from market_cell.graph.models import GraphNodeRole
from market_cell.inputs import InputKind, InputReference


CELL_EXECUTION_PLAN_SCHEMA_VERSION = "cell_execution_plan.v5"
CELL_RUNTIME_TRACE_SCHEMA_VERSION = "cell_runtime_trace.v1"
CELL_RUNTIME_SUMMARY_SCHEMA_VERSION = "cell_runtime_summary.v1"
EXECUTION_CONTROL_RECORD_SCHEMA_VERSION = "execution_control_record.v1"

CellRuntime = Literal["python_local", "python_service", "rust_service", "external_service"]
ExecutionRole = GraphNodeRole
CpuWeight = Literal["unknown", "light", "medium", "heavy"]
LatencySensitivity = Literal["low", "normal", "high"]
RuntimeTraceStatus = Literal["succeeded", "failed", "skipped"]
ExecutionFailureKind = Literal[
    "routing",
    "dispatch",
    "execution",
    "timeout",
    "backpressure",
    "canceled",
    "contract",
]
ExecutionAttemptStatus = Literal[
    "succeeded",
    "failed",
    "timed_out",
    "backpressured",
    "canceled",
]
ExecutionControlStatus = Literal["succeeded", "failed", "canceled"]


def service_binding_id(implementation_id: str, service_id: str) -> str:
    return f"binding:{service_id}:{implementation_id}"


@dataclass(frozen=True)
class ResourceHints:
    cpu_weight: CpuWeight = "unknown"
    latency_sensitivity: LatencySensitivity = "normal"
    stateful: bool = False
    expected_timeout_ms: int = 30_000
    max_retries: int = 0

    def __post_init__(self) -> None:
        if self.expected_timeout_ms < 1:
            raise ValueError("expected_timeout_ms must be at least 1")
        if self.max_retries < 0:
            raise ValueError("max_retries must not be negative")


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
        required_values = {
            "implementation_id": self.implementation_id,
            "cell_id": self.cell_id,
            "service_id": self.service_id,
            "language": self.language,
            "formula_version": self.formula_version,
        }
        for field_name, value in required_values.items():
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.priority < 0:
            raise ValueError("priority must not be negative")
        if self.max_concurrency is not None and self.max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
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
    fallback_binding_ids: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    input_reference_ids: list[str] = field(default_factory=list)
    required_input_kinds: list[InputKind] = field(
        default_factory=lambda: ["analysis_request"]
    )
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
    input_references: list[InputReference]
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

    def __post_init__(self) -> None:
        if self.duration_ms < 0:
            raise ValueError("duration_ms must not be negative")
        if self.retry_count < 0:
            raise ValueError("retry_count must not be negative")

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


@dataclass(frozen=True)
class CellExecutionAttempt:
    attempt_id: str
    idempotency_key: str
    attempt_number: int
    binding_attempt_number: int
    fallback_index: int
    binding_id: str
    is_retry: bool
    status: ExecutionAttemptStatus
    failure_kind: ExecutionFailureKind | None
    retryable: bool
    started_at: str
    finished_at: str
    duration_ms: float
    trace_span_id: str | None
    actual_implementation_id: str | None
    actual_service_id: str | None
    actual_runtime: CellRuntime | None
    error: str | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be at least 1")
        if self.binding_attempt_number < 1:
            raise ValueError("binding_attempt_number must be at least 1")
        if self.fallback_index < 0:
            raise ValueError("fallback_index must not be negative")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must not be negative")
        if self.is_retry != (self.binding_attempt_number > 1):
            raise ValueError("is_retry must match binding_attempt_number")
        if self.status == "succeeded":
            if self.failure_kind is not None or self.error is not None:
                raise ValueError("successful attempt cannot contain failure details")
            if self.retryable:
                raise ValueError("successful attempt cannot be retryable")
        elif self.failure_kind is None or self.error is None:
            raise ValueError("failed attempt requires failure_kind and error")
        expected_failure_kind = {
            "timed_out": "timeout",
            "backpressured": "backpressure",
            "canceled": "canceled",
        }.get(self.status)
        if (
            expected_failure_kind is not None
            and self.failure_kind != expected_failure_kind
        ):
            raise ValueError(
                f"attempt status {self.status} requires {expected_failure_kind} failure"
            )
        if self.status == "failed" and self.failure_kind in {
            "timeout",
            "backpressure",
            "canceled",
        }:
            raise ValueError("specialized failure kind requires specialized attempt status")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionControlRecord:
    control_id: str
    idempotency_key: str
    run_id: str
    plan_id: str
    node_id: str
    primary_binding_id: str
    fallback_binding_ids: list[str]
    status: ExecutionControlStatus
    attempts: list[CellExecutionAttempt]
    retry_count: int
    fallback_count: int
    final_binding_id: str
    final_failure_kind: ExecutionFailureKind | None
    started_at: str
    finished_at: str
    schema_version: str = EXECUTION_CONTROL_RECORD_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.attempts:
            raise ValueError("execution control record requires at least one attempt")
        attempt_numbers = [attempt.attempt_number for attempt in self.attempts]
        if attempt_numbers != list(range(1, len(self.attempts) + 1)):
            raise ValueError("execution attempts must have contiguous attempt numbers")
        if len({attempt.attempt_id for attempt in self.attempts}) != len(self.attempts):
            raise ValueError("execution attempt_id values must be unique")
        if any(attempt.idempotency_key != self.idempotency_key for attempt in self.attempts):
            raise ValueError("execution attempts must share the control idempotency key")
        binding_ids = [self.primary_binding_id, *self.fallback_binding_ids]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("control primary and fallback binding ids must be unique")
        if self.attempts[0].fallback_index != 0:
            raise ValueError("execution attempts must start with the primary binding")
        previous_fallback_index = 0
        binding_attempt_counts: dict[int, int] = {}
        for attempt in self.attempts:
            if attempt.fallback_index >= len(binding_ids):
                raise ValueError("attempt fallback_index is outside configured bindings")
            if attempt.binding_id != binding_ids[attempt.fallback_index]:
                raise ValueError("attempt binding_id does not match fallback_index")
            if attempt.fallback_index not in {
                previous_fallback_index,
                previous_fallback_index + 1,
            }:
                raise ValueError("execution attempts must follow fallback order")
            if attempt.fallback_index < previous_fallback_index:
                raise ValueError("execution attempts cannot return to an earlier binding")
            binding_attempt_counts[attempt.fallback_index] = (
                binding_attempt_counts.get(attempt.fallback_index, 0) + 1
            )
            if (
                attempt.binding_attempt_number
                != binding_attempt_counts[attempt.fallback_index]
            ):
                raise ValueError(
                    "binding_attempt_number must be contiguous for each binding"
                )
            previous_fallback_index = attempt.fallback_index
        if self.retry_count != sum(attempt.is_retry for attempt in self.attempts):
            raise ValueError("retry_count does not match execution attempts")
        if self.fallback_count != max(attempt.fallback_index for attempt in self.attempts):
            raise ValueError("fallback_count does not match execution attempts")
        final_attempt = self.attempts[-1]
        if self.final_binding_id != final_attempt.binding_id:
            raise ValueError("final_binding_id does not match the final attempt")
        if self.final_failure_kind != final_attempt.failure_kind:
            raise ValueError("final_failure_kind does not match the final attempt")
        expected_status: ExecutionControlStatus
        if final_attempt.status == "succeeded":
            expected_status = "succeeded"
        elif final_attempt.status == "canceled":
            expected_status = "canceled"
        else:
            expected_status = "failed"
        if self.status != expected_status:
            raise ValueError("control status does not match the final attempt")

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }
