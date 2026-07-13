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
    CellRuntimeTrace,
    CellServiceBinding,
)
from market_cell.models import AnalysisRequest, CellResult


class CellExecutionError(RuntimeError):
    pass


class CellExecutionBindingError(CellExecutionError):
    pass


class CellResultContractError(CellExecutionError):
    pass


class ExecutionTraceMismatchError(CellExecutionError):
    pass


@dataclass(frozen=True)
class CellExecutionContext:
    run_id: str
    trace_id: str
    plan_id: str | None = None
    node: CellExecutionNode | None = None
    binding: CellServiceBinding | None = None


@dataclass(frozen=True)
class CellExecutionOutcome:
    trace: CellRuntimeTrace
    result: CellResult | None = None
    error: Exception | None = field(default=None, repr=False, compare=False)

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
        trace_metadata = _trace_metadata(self.name, context.binding)

        try:
            _validate_local_execution_context(
                manifest_cell_id=manifest.cell_id,
                formula_version=manifest.formula_version,
                actual_binding=actual_binding,
                context=context,
            )
            result = cell.analyze(request, child_results)
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
    binding = next(
        (
            item
            for item in execution_plan.service_bindings
            if item.cell_id == trace.cell_id
            and item.implementation_id == trace.implementation_id
        ),
        None,
    )
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
        if trace.implementation_id != node.implementation_id:
            mismatches.append("implementation_id")
    if binding is None:
        mismatches.append("service_binding")
    else:
        if trace.service_id != binding.service_id:
            mismatches.append("service_id")
        if trace.runtime != binding.runtime:
            mismatches.append("runtime")
    if mismatches:
        raise ExecutionTraceMismatchError(
            f"trace {trace.span_id} does not match plan {execution_plan.plan_id}: "
            f"{', '.join(sorted(set(mismatches)))}"
        )


def _validate_local_execution_context(
    *,
    manifest_cell_id: str,
    formula_version: str,
    actual_binding: CellServiceBinding,
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
    if context.node.implementation_id != context.binding.implementation_id:
        mismatches.append("node_binding_implementation")
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
    planned_binding: CellServiceBinding | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "executor": executor_name,
        "planned_binding": planned_binding is not None,
    }
    if planned_binding is not None:
        metadata.update(
            {
                "planned_implementation_id": planned_binding.implementation_id,
                "planned_service_id": planned_binding.service_id,
                "planned_runtime": planned_binding.runtime,
            }
        )
    return metadata


def _duration_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 6)
