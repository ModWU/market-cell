from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from market_cell.execution.control import validate_execution_control_record
from market_cell.execution.executor import (
    CancellationSignal,
    CellExecutionContext,
    CellExecutor,
    validate_cell_result,
    validate_execution_trace,
)
from market_cell.execution.models import (
    CellRuntimeTrace,
    ExecutionControlRecord,
    ExecutionRole,
)
from market_cell.execution.plan_validation import ValidatedExecutionPlan
from market_cell.inputs import (
    CellInputBundle,
    InputCompositionError,
    InputKind,
    InputReference,
    InputResolutionError,
    InputResolutionRecord,
    InputResolutionStatus,
    InputResolver,
    InputSnapshot,
    ResolvedCellInput,
)
from market_cell.models import AnalysisRequest, CellResult
from market_cell.registry import CellRegistry


PLAN_EXECUTION_SCHEMA_VERSION = "plan_execution.v1"


@dataclass(frozen=True)
class NodeExecutionCompletion:
    node_id: str
    cell_id: str
    binding_id: str
    execution_role: ExecutionRole
    input_reference_ids: list[str]
    result: CellResult | None
    trace: CellRuntimeTrace | None
    control_record: ExecutionControlRecord | None = None
    error: Exception | None = field(default=None, repr=False, compare=False)


NodeCompletionHandler = Callable[[NodeExecutionCompletion], None]


@dataclass(frozen=True)
class PlanExecutionOutcome:
    coordinator: str
    plan_id: str
    root_node_id: str
    results_by_node_id: dict[str, CellResult]
    runtime_traces: list[CellRuntimeTrace]
    execution_control_records: list[ExecutionControlRecord]
    input_resolution_records: list[InputResolutionRecord]
    execution_order: list[str]
    root_result: CellResult | None = None
    failed_node_id: str | None = None
    error: Exception | None = field(default=None, repr=False, compare=False)
    schema_version: str = PLAN_EXECUTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.error is None:
            if self.root_result is None or self.failed_node_id is not None:
                raise ValueError(
                    "successful plan execution requires a root result and no failed node"
                )
            if self.root_node_id not in self.results_by_node_id:
                raise ValueError("root result must be stored by root_node_id")
            return
        if self.root_result is not None or self.failed_node_id is None:
            raise ValueError(
                "failed plan execution requires an error and failed_node_id"
            )

    @property
    def succeeded(self) -> bool:
        return self.root_result is not None and self.error is None

    def unwrap(self) -> CellResult:
        if self.error is not None:
            raise self.error
        if self.root_result is None:
            raise RuntimeError(
                f"plan {self.plan_id} completed without root result {self.root_node_id}"
            )
        return self.root_result

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "coordinator": self.coordinator,
            "plan_id": self.plan_id,
            "root_node_id": self.root_node_id,
            "status": "succeeded" if self.succeeded else "failed",
            "execution_order": list(self.execution_order),
            "completed_node_ids": list(self.results_by_node_id),
            "failed_node_id": self.failed_node_id,
            "error": str(self.error) if self.error is not None else None,
        }

    def to_run_metadata(self) -> dict[str, object]:
        return {"plan_execution": self.to_dict()}


class CellExecutionCoordinator(Protocol):
    @property
    def name(self) -> str:
        ...

    def execute(
        self,
        *,
        validated_plan: ValidatedExecutionPlan,
        registry: CellRegistry,
        executor: CellExecutor,
        input_resolver: InputResolver,
        run_id: str,
        trace_id: str,
        on_node_completed: NodeCompletionHandler | None = None,
        cancellation_signal: CancellationSignal | None = None,
    ) -> PlanExecutionOutcome:
        ...


class PlanDrivenLocalCoordinator:
    @property
    def name(self) -> str:
        return "plan_driven_local_coordinator_v0.2"

    def execute(
        self,
        *,
        validated_plan: ValidatedExecutionPlan,
        registry: CellRegistry,
        executor: CellExecutor,
        input_resolver: InputResolver,
        run_id: str,
        trace_id: str,
        on_node_completed: NodeCompletionHandler | None = None,
        cancellation_signal: CancellationSignal | None = None,
    ) -> PlanExecutionOutcome:
        plan = validated_plan.plan
        nodes_by_id = {node.node_id: node for node in plan.nodes}
        bindings_by_id = {
            binding.binding_id: binding for binding in plan.service_bindings
        }
        references_by_id = {
            reference.reference_id: reference for reference in plan.input_references
        }
        results_by_node_id: dict[str, CellResult] = {}
        runtime_traces: list[CellRuntimeTrace] = []
        execution_control_records: list[ExecutionControlRecord] = []
        input_resolution_records: list[InputResolutionRecord] = []
        resolved_inputs: dict[str, InputSnapshot] = {}
        materialized_requests: dict[str, AnalysisRequest] = {}
        execution_order: list[str] = []

        for level in validated_plan.topological_levels:
            for node_id in level:
                node = nodes_by_id[node_id]
                binding = bindings_by_id[node.binding_id]
                execution_order.append(node_id)
                trace: CellRuntimeTrace | None = None
                control_record: ExecutionControlRecord | None = None
                try:
                    cell = registry.resolve(node.cell_id)
                    input_bundle = _compose_cell_inputs(
                        node_id=node.node_id,
                        reference_ids=node.input_reference_ids,
                        required_input_kinds=node.required_input_kinds,
                        references_by_id=references_by_id,
                        input_resolver=input_resolver,
                        resolved_inputs=resolved_inputs,
                        materialized_requests=materialized_requests,
                        resolution_records=input_resolution_records,
                    )
                    request = input_bundle.analysis_request
                    child_results = (
                        [results_by_node_id[dependency_id] for dependency_id in node.dependencies]
                        if node.dependencies
                        else None
                    )
                    execution_context = CellExecutionContext(
                        run_id=run_id,
                        trace_id=trace_id,
                        plan_id=plan.plan_id,
                        node=node,
                        binding=binding,
                        input_bundle=input_bundle,
                        fallback_bindings=tuple(
                            bindings_by_id[binding_id]
                            for binding_id in node.fallback_binding_ids
                        ),
                        cancellation_signal=cancellation_signal,
                    )
                    cell_outcome = executor.execute(
                        cell=cell,
                        request=request,
                        child_results=child_results,
                        context=execution_context,
                    )
                    trace = cell_outcome.trace
                    runtime_traces.extend(cell_outcome.runtime_traces)
                    control_record = cell_outcome.control_record
                    if control_record is not None:
                        execution_control_records.append(control_record)
                        validate_execution_control_record(
                            control_record,
                            execution_context,
                            cell_outcome.runtime_traces,
                        )
                    for attempt_trace in cell_outcome.runtime_traces:
                        validate_execution_trace(attempt_trace, plan)
                    result = cell_outcome.unwrap()
                    validate_cell_result(cell, request, result)
                except Exception as exc:
                    completion = NodeExecutionCompletion(
                        node_id=node.node_id,
                        cell_id=node.cell_id,
                        binding_id=node.binding_id,
                        execution_role=node.execution_role,
                        input_reference_ids=list(node.input_reference_ids),
                        result=None,
                        trace=trace,
                        control_record=control_record,
                        error=exc,
                    )
                    if on_node_completed is not None:
                        on_node_completed(completion)
                    return PlanExecutionOutcome(
                        coordinator=self.name,
                        plan_id=plan.plan_id,
                        root_node_id=plan.root_node_id,
                        results_by_node_id=results_by_node_id,
                        runtime_traces=runtime_traces,
                        execution_control_records=execution_control_records,
                        input_resolution_records=input_resolution_records,
                        execution_order=execution_order,
                        failed_node_id=node.node_id,
                        error=exc,
                    )

                results_by_node_id[node.node_id] = result
                if on_node_completed is not None:
                    on_node_completed(
                        NodeExecutionCompletion(
                            node_id=node.node_id,
                            cell_id=node.cell_id,
                            binding_id=node.binding_id,
                            execution_role=node.execution_role,
                            input_reference_ids=list(node.input_reference_ids),
                            result=result,
                            trace=trace,
                            control_record=control_record,
                        )
                    )

        root_result = results_by_node_id.get(plan.root_node_id)
        if root_result is None:
            error = RuntimeError(
                f"plan {plan.plan_id} completed without root result {plan.root_node_id}"
            )
            return PlanExecutionOutcome(
                coordinator=self.name,
                plan_id=plan.plan_id,
                root_node_id=plan.root_node_id,
                results_by_node_id=results_by_node_id,
                runtime_traces=runtime_traces,
                execution_control_records=execution_control_records,
                input_resolution_records=input_resolution_records,
                execution_order=execution_order,
                failed_node_id=plan.root_node_id,
                error=error,
            )
        return PlanExecutionOutcome(
            coordinator=self.name,
            plan_id=plan.plan_id,
            root_node_id=plan.root_node_id,
            results_by_node_id=results_by_node_id,
            runtime_traces=runtime_traces,
            execution_control_records=execution_control_records,
            input_resolution_records=input_resolution_records,
            execution_order=execution_order,
            root_result=root_result,
        )


def _compose_cell_inputs(
    *,
    node_id: str,
    reference_ids: list[str],
    required_input_kinds: list[InputKind],
    references_by_id: dict[str, InputReference],
    input_resolver: InputResolver,
    resolved_inputs: dict[str, InputSnapshot],
    materialized_requests: dict[str, AnalysisRequest],
    resolution_records: list[InputResolutionRecord],
) -> CellInputBundle:
    snapshots_by_reference_id: dict[str, InputSnapshot] = {}
    for reference_id in reference_ids:
        reference = references_by_id[reference_id]
        cache_hit = reference_id in resolved_inputs
        if cache_hit:
            snapshot = resolved_inputs[reference_id]
        else:
            try:
                snapshot = input_resolver.resolve(reference)
            except Exception as exc:
                resolution_records.append(
                    _resolution_record(
                        node_id=node_id,
                        reference=reference,
                        resolver=input_resolver.name,
                        status="failed",
                        cache_hit=False,
                        actual_content_hash=(
                            exc.actual_content_hash
                            if isinstance(exc, InputResolutionError)
                            else None
                        ),
                        actual_payload_size_bytes=(
                            exc.actual_payload_size_bytes
                            if isinstance(exc, InputResolutionError)
                            else None
                        ),
                        error=str(exc),
                    )
                )
                raise
            resolved_inputs[reference_id] = snapshot
        resolution_records.append(
            _resolution_record(
                node_id=node_id,
                reference=reference,
                resolver=input_resolver.name,
                status="succeeded",
                cache_hit=cache_hit,
                actual_content_hash=snapshot.content_hash,
                actual_payload_size_bytes=snapshot.payload_size_bytes,
            )
        )
        snapshots_by_reference_id[reference_id] = snapshot

    request_reference_ids = [
        reference_id
        for reference_id, snapshot in snapshots_by_reference_id.items()
        if snapshot.input_kind == "analysis_request"
    ]
    if len(request_reference_ids) != 1:
        raise InputCompositionError(
            f"node {node_id} requires exactly one analysis_request input, "
            f"received {len(request_reference_ids)}"
        )
    request_reference_id = request_reference_ids[0]
    if request_reference_id not in materialized_requests:
        try:
            materialized_requests[request_reference_id] = snapshots_by_reference_id[
                request_reference_id
            ].to_analysis_request()
        except Exception as exc:
            raise InputCompositionError(
                f"node {node_id} could not materialize analysis_request "
                f"{request_reference_id}"
            ) from exc
    request = materialized_requests[request_reference_id]
    try:
        return CellInputBundle(
            node_id=node_id,
            analysis_request=request,
            resolved_inputs=tuple(
                ResolvedCellInput(
                    reference=references_by_id[reference_id],
                    snapshot=snapshots_by_reference_id[reference_id],
                )
                for reference_id in reference_ids
            ),
            required_input_kinds=tuple(required_input_kinds),
        )
    except ValueError as exc:
        raise InputCompositionError(
            f"node {node_id} could not compose its typed input bundle: {exc}"
        ) from exc


def _resolution_record(
    *,
    node_id: str,
    reference: InputReference,
    resolver: str,
    status: InputResolutionStatus,
    cache_hit: bool,
    actual_content_hash: str | None,
    actual_payload_size_bytes: int | None,
    error: str | None = None,
) -> InputResolutionRecord:
    return InputResolutionRecord(
        node_id=node_id,
        reference_id=reference.reference_id,
        input_kind=reference.input_kind,
        resolver=resolver,
        status=status,
        cache_hit=cache_hit,
        expected_content_hash=reference.content_hash,
        actual_content_hash=actual_content_hash,
        expected_payload_size_bytes=reference.payload_size_bytes,
        actual_payload_size_bytes=actual_payload_size_bytes,
        data_version=reference.data_version,
        source=reference.source,
        error=error,
    )
