from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Protocol
from uuid import uuid4

from market_cell.cells.base import MarketCell
from market_cell.events import utc_now_iso
from market_cell.execution.catalog import build_local_service_binding
from market_cell.execution.models import (
    CellExecutionNode,
    CellExecutionPlan,
    ExecutionControlRecord,
    CellRuntimeTrace,
    CellServiceBinding,
)
from market_cell.inputs import CellInputBundle
from market_cell.models import AnalysisRequest, CellResult


class CellExecutionError(RuntimeError):
    pass


class CellExecutionBindingError(CellExecutionError):
    pass


class CellResultContractError(CellExecutionError):
    pass


class ExecutionTraceMismatchError(CellExecutionError):
    pass


class CancellationSignal(Protocol):
    def is_cancellation_requested(self) -> bool:
        ...


@dataclass(frozen=True)
class CellExecutionContext:
    run_id: str
    trace_id: str
    plan_id: str | None = None
    node: CellExecutionNode | None = None
    binding: CellServiceBinding | None = None
    input_bundle: CellInputBundle | None = None
    fallback_bindings: tuple[CellServiceBinding, ...] = ()
    idempotency_key: str | None = None
    attempt_id: str | None = None
    attempt_number: int = 0
    timeout_ms: int | None = None
    cancellation_signal: CancellationSignal | None = field(
        default=None,
        repr=False,
        compare=False,
    )


@dataclass(frozen=True)
class CellExecutionOutcome:
    trace: CellRuntimeTrace
    result: CellResult | None = None
    error: Exception | None = field(default=None, repr=False, compare=False)
    prior_traces: tuple[CellRuntimeTrace, ...] = ()
    control_record: ExecutionControlRecord | None = None

    def __post_init__(self) -> None:
        succeeded = self.result is not None and self.error is None
        failed = self.result is None and self.error is not None
        if not succeeded and not failed:
            raise ValueError("execution outcome must contain exactly one of result or error")
        expected_status = "succeeded" if succeeded else "failed"
        if self.trace.status != expected_status:
            raise ValueError(
                f"execution outcome status {self.trace.status} does not match {expected_status}"
            )
        span_ids = [trace.span_id for trace in [*self.prior_traces, self.trace]]
        if len(span_ids) != len(set(span_ids)):
            raise ValueError("execution outcome trace span_id values must be unique")

    @property
    def runtime_traces(self) -> list[CellRuntimeTrace]:
        return [*self.prior_traces, self.trace]

    def unwrap(self) -> CellResult:
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise CellExecutionError("execution completed without a CellResult")
        return self.result


class CellExecutor(Protocol):
    @property
    def name(self) -> str:
        ...

    def execute(
        self,
        *,
        cell: MarketCell,
        request: AnalysisRequest,
        context: CellExecutionContext,
        child_results: list[CellResult] | None = None,
    ) -> CellExecutionOutcome:
        ...


class LocalCellExecutor:
    def __init__(self, service_id: str = "python-local") -> None:
        if not service_id.strip():
            raise ValueError("service_id must not be empty")
        self.service_id = service_id

    @property
    def name(self) -> str:
        return "local_python_executor_v0.1"

    def execute(
        self,
        *,
        cell: MarketCell,
        request: AnalysisRequest,
        context: CellExecutionContext,
        child_results: list[CellResult] | None = None,
    ) -> CellExecutionOutcome:
        manifest = cell.manifest()
        actual_binding = build_local_service_binding(manifest, self.service_id)
        started_at = utc_now_iso()
        started = perf_counter()
        trace_metadata = _trace_metadata(self.name, context)

        try:
            _validate_local_execution_context(
                manifest_cell_id=manifest.cell_id,
                formula_version=manifest.formula_version,
                required_input_kinds=manifest.required_input_kinds,
                actual_binding=actual_binding,
                request=request,
                context=context,
            )
            result = (
                cell.analyze_inputs(context.input_bundle, child_results)
                if context.input_bundle is not None
                else cell.analyze(request, child_results)
            )
            validate_cell_result(cell, request, result)
        except Exception as exc:
            trace = _runtime_trace(
                context=context,
                actual_binding=actual_binding,
                cell_id=manifest.cell_id,
                formula_version=manifest.formula_version,
                status="failed",
                started_at=started_at,
                duration_ms=_duration_ms(started),
                error=str(exc),
                metadata=trace_metadata,
            )
            return CellExecutionOutcome(trace=trace, error=exc)

        trace = _runtime_trace(
            context=context,
            actual_binding=actual_binding,
            cell_id=manifest.cell_id,
            formula_version=manifest.formula_version,
            status="succeeded",
            started_at=started_at,
            duration_ms=_duration_ms(started),
            metadata=trace_metadata,
        )
        return CellExecutionOutcome(trace=trace, result=result)


def validate_execution_trace(
    trace: CellRuntimeTrace,
    execution_plan: CellExecutionPlan | None,
) -> None:
    if execution_plan is None:
        if trace.plan_id is not None:
            raise ExecutionTraceMismatchError(
                f"trace {trace.span_id} references plan {trace.plan_id} without an execution plan"
            )
        return

    node = next(
        (item for item in execution_plan.nodes if item.node_id == trace.node_id),
        None,
    )
    allowed_binding_ids = (
        {node.binding_id, *node.fallback_binding_ids}
        if node is not None
        else set()
    )
    allowed_bindings = [
        item
        for item in execution_plan.service_bindings
        if item.binding_id in allowed_binding_ids
    ]
    mismatches: list[str] = []
    if trace.plan_id != execution_plan.plan_id:
        mismatches.append("plan_id")
    if node is None:
        mismatches.append("node_id")
    else:
        if trace.cell_id != node.cell_id:
            mismatches.append("cell_id")
        if trace.formula_version != node.formula_version:
            mismatches.append("formula_version")
    actual_identity = (
        trace.implementation_id,
        trace.service_id,
        trace.runtime,
    )
    if actual_identity == (None, None, None):
        planned_binding_id = trace.metadata.get("planned_binding_id")
        planned_binding = next(
            (
                item
                for item in allowed_bindings
                if item.binding_id == planned_binding_id
            ),
            None,
        )
        if trace.status != "failed" or planned_binding is None:
            mismatches.append("service_binding")
        else:
            planned_metadata = {
                "planned_implementation_id": planned_binding.implementation_id,
                "planned_service_id": planned_binding.service_id,
                "planned_runtime": planned_binding.runtime,
            }
            if any(
                trace.metadata.get(key) != value
                for key, value in planned_metadata.items()
            ):
                mismatches.append("planned_service_binding")
            if (
                node is not None
                and planned_binding.binding_id != node.binding_id
                and _trace_fallback_index(trace) is None
            ):
                mismatches.append("fallback_control")
    else:
        matching_binding = next(
            (
                item
                for item in allowed_bindings
                if actual_identity
                == (item.implementation_id, item.service_id, item.runtime)
            ),
            None,
        )
        if matching_binding is None:
            mismatches.append("service_binding")
        elif node is not None and matching_binding.binding_id != node.binding_id:
            if _trace_fallback_index(trace) is None:
                mismatches.append("fallback_control")
    if mismatches:
        raise ExecutionTraceMismatchError(
            f"trace {trace.span_id} does not match plan {execution_plan.plan_id}: "
            f"{', '.join(sorted(set(mismatches)))}"
        )


def _trace_fallback_index(trace: CellRuntimeTrace) -> int | None:
    execution_control = trace.metadata.get("execution_control")
    if not isinstance(execution_control, dict):
        return None
    fallback_index = execution_control.get("fallback_index")
    if not isinstance(fallback_index, int) or fallback_index < 1:
        return None
    return fallback_index


def validate_execution_trace_context(
    trace: CellRuntimeTrace,
    context: CellExecutionContext,
) -> None:
    mismatches: list[str] = []
    if trace.run_id != context.run_id:
        mismatches.append("run_id")
    if trace.trace_id != context.trace_id:
        mismatches.append("trace_id")
    if trace.plan_id != context.plan_id:
        mismatches.append("plan_id")

    if context.node is None:
        mismatches.append("node")
    else:
        if trace.node_id != context.node.node_id:
            mismatches.append("node_id")
        if trace.cell_id != context.node.cell_id:
            mismatches.append("cell_id")
        if trace.formula_version != context.node.formula_version:
            mismatches.append("formula_version")

    if context.binding is None:
        mismatches.append("binding")
    else:
        if context.node is not None:
            if context.node.binding_id != context.binding.binding_id:
                mismatches.append("node_binding_id")
            if context.node.cell_id != context.binding.cell_id:
                mismatches.append("binding_cell_id")
            if context.node.formula_version != context.binding.formula_version:
                mismatches.append("binding_formula_version")
        if trace.implementation_id != context.binding.implementation_id:
            mismatches.append("implementation_id")
        if trace.service_id != context.binding.service_id:
            mismatches.append("service_id")
        if trace.runtime != context.binding.runtime:
            mismatches.append("runtime")

    if mismatches:
        raise ExecutionTraceMismatchError(
            f"trace {trace.span_id} does not match execution context: "
            f"{', '.join(sorted(set(mismatches)))}"
        )


def _validate_local_execution_context(
    *,
    manifest_cell_id: str,
    formula_version: str,
    required_input_kinds: list[str],
    actual_binding: CellServiceBinding,
    request: AnalysisRequest,
    context: CellExecutionContext,
) -> None:
    if context.node is None and context.binding is None:
        return
    if context.node is None or context.binding is None:
        raise CellExecutionBindingError("execution plan must provide both node and binding")

    mismatches: list[str] = []
    if context.node.cell_id != manifest_cell_id or context.binding.cell_id != manifest_cell_id:
        mismatches.append("cell_id")
    if (
        context.node.formula_version != formula_version
        or context.binding.formula_version != formula_version
    ):
        mismatches.append("formula_version")
    if context.node.binding_id != context.binding.binding_id:
        mismatches.append("node_binding_id")
    if context.node.required_input_kinds != required_input_kinds:
        mismatches.append("required_input_kinds")
    if context.input_bundle is None:
        mismatches.append("input_bundle")
    else:
        if context.input_bundle.node_id != context.node.node_id:
            mismatches.append("input_bundle_node_id")
        if list(context.input_bundle.required_input_kinds) != required_input_kinds:
            mismatches.append("input_bundle_required_input_kinds")
        if [
            item.reference.reference_id
            for item in context.input_bundle.resolved_inputs
        ] != context.node.input_reference_ids:
            mismatches.append("input_bundle_reference_ids")
        if context.input_bundle.analysis_request != request:
            mismatches.append("input_bundle_analysis_request")
    if context.binding.binding_id != actual_binding.binding_id:
        mismatches.append("binding_id")
    if context.binding.implementation_id != actual_binding.implementation_id:
        mismatches.append("implementation_id")
    if context.binding.service_id != actual_binding.service_id:
        mismatches.append("service_id")
    if context.binding.runtime != actual_binding.runtime:
        mismatches.append("runtime")
    if context.binding.language != actual_binding.language:
        mismatches.append("language")
    if mismatches:
        raise CellExecutionBindingError(
            f"local executor {actual_binding.service_id} rejected binding for "
            f"{manifest_cell_id}@{formula_version}: {', '.join(sorted(set(mismatches)))}"
        )


def validate_cell_result(
    cell: MarketCell,
    request: AnalysisRequest,
    result: CellResult,
) -> None:
    if not isinstance(result, CellResult):
        raise CellResultContractError(
            f"{cell.cell_id} returned {type(result).__name__}, expected CellResult"
        )
    mismatches: list[str] = []
    if result.cell_id != cell.cell_id:
        mismatches.append("cell_id")
    if result.target != request.target:
        mismatches.append("target")
    if result.horizon != request.horizon:
        mismatches.append("horizon")
    if mismatches:
        raise CellResultContractError(
            f"{cell.cell_id} returned an incompatible CellResult: "
            f"{', '.join(mismatches)}"
        )


def _runtime_trace(
    *,
    context: CellExecutionContext,
    actual_binding: CellServiceBinding,
    cell_id: str,
    formula_version: str,
    status: str,
    started_at: str,
    duration_ms: float,
    metadata: dict[str, Any],
    error: str | None = None,
) -> CellRuntimeTrace:
    return CellRuntimeTrace(
        trace_id=context.trace_id,
        span_id=uuid4().hex,
        run_id=context.run_id,
        plan_id=context.plan_id,
        node_id=context.node.node_id if context.node is not None else f"cell:{cell_id}",
        cell_id=cell_id,
        implementation_id=actual_binding.implementation_id,
        service_id=actual_binding.service_id,
        runtime=actual_binding.runtime,
        formula_version=formula_version,
        status=status,
        started_at=started_at,
        finished_at=utc_now_iso(),
        duration_ms=duration_ms,
        error=error,
        metadata=metadata,
    )


def _trace_metadata(
    executor_name: str,
    context: CellExecutionContext,
) -> dict[str, Any]:
    planned_binding = context.binding
    metadata: dict[str, Any] = {
        "executor": executor_name,
        "planned_binding": planned_binding is not None,
        "input_reference_ids": (
            list(context.node.input_reference_ids)
            if context.node is not None
            else []
        ),
        **cell_input_trace_metadata(context),
    }
    if planned_binding is not None:
        metadata.update(
            {
                "planned_implementation_id": planned_binding.implementation_id,
                "planned_binding_id": planned_binding.binding_id,
                "planned_service_id": planned_binding.service_id,
                "planned_runtime": planned_binding.runtime,
            }
        )
    return metadata


def cell_input_trace_metadata(
    context: CellExecutionContext,
) -> dict[str, Any]:
    bundle = context.input_bundle
    if bundle is None:
        return {}
    return {
        "input_bundle_schema_version": bundle.schema_version,
        "input_kinds": list(bundle.required_input_kinds),
        "input_snapshot_ids": [
            item.snapshot.snapshot_id for item in bundle.resolved_inputs
        ],
    }


def _duration_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 6)
