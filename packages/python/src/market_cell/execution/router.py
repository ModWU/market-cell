from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter
from typing import Literal, Mapping, get_args
from uuid import uuid4

from market_cell.cells.base import MarketCell
from market_cell.events import utc_now_iso
from market_cell.execution.executor import (
    CellExecutionContext,
    CellExecutionError,
    CellExecutionOutcome,
    CellExecutor,
    ExecutionTraceMismatchError,
    cell_input_trace_metadata,
    validate_execution_trace_context,
)
from market_cell.execution.models import (
    CellRuntime,
    CellRuntimeTrace,
    CellServiceBinding,
)
from market_cell.models import AnalysisRequest, CellResult


ExecutorRouteKind = Literal["service", "runtime"]


class ExecutorRoutingError(CellExecutionError):
    pass


class ExecutorRouteNotFoundError(ExecutorRoutingError):
    pass


class ExecutorDispatchError(ExecutorRoutingError):
    pass


@dataclass(frozen=True)
class ExecutorRoute:
    kind: ExecutorRouteKind
    key: str
    executor: CellExecutor


class ExecutorRouter:
    """Routes one planned node without changing its selected service binding."""

    def __init__(
        self,
        *,
        service_routes: Mapping[str, CellExecutor] | None = None,
        runtime_routes: Mapping[CellRuntime, CellExecutor] | None = None,
    ) -> None:
        self._service_routes = _validated_routes(service_routes or {}, "service_id")
        self._runtime_routes = _validated_routes(runtime_routes or {}, "runtime")

    @property
    def name(self) -> str:
        return "executor_router_v0.1"

    def resolve_route(self, binding: CellServiceBinding) -> ExecutorRoute:
        service_executor = self._service_routes.get(binding.service_id)
        if service_executor is not None:
            return ExecutorRoute(
                kind="service",
                key=binding.service_id,
                executor=service_executor,
            )

        runtime_executor = self._runtime_routes.get(binding.runtime)
        if runtime_executor is not None:
            return ExecutorRoute(
                kind="runtime",
                key=binding.runtime,
                executor=runtime_executor,
            )

        raise ExecutorRouteNotFoundError(
            f"no executor route for binding {binding.binding_id} "
            f"(service_id={binding.service_id}, runtime={binding.runtime})"
        )

    def execute(
        self,
        *,
        cell: MarketCell,
        request: AnalysisRequest,
        context: CellExecutionContext,
        child_results: list[CellResult] | None = None,
    ) -> CellExecutionOutcome:
        started_at = utc_now_iso()
        started = perf_counter()
        if (
            context.plan_id is None
            or context.node is None
            or context.binding is None
        ):
            error = ExecutorRouteNotFoundError(
                "executor router requires plan_id, execution node, and service binding"
            )
            return _routing_failure(
                router_name=self.name,
                cell=cell,
                context=context,
                error=error,
                started_at=started_at,
                duration_ms=_duration_ms(started),
            )

        try:
            route = self.resolve_route(context.binding)
        except ExecutorRouteNotFoundError as exc:
            return _routing_failure(
                router_name=self.name,
                cell=cell,
                context=context,
                error=exc,
                started_at=started_at,
                duration_ms=_duration_ms(started),
            )

        try:
            outcome = route.executor.execute(
                cell=cell,
                request=request,
                context=context,
                child_results=child_results,
            )
            if not isinstance(outcome, CellExecutionOutcome):
                raise TypeError(
                    f"executor {route.executor.name} returned "
                    f"{type(outcome).__name__}, expected CellExecutionOutcome"
                )
        except Exception as exc:
            error = ExecutorDispatchError(
                f"executor {route.executor.name} raised while dispatching "
                f"binding {context.binding.binding_id}: {exc}"
            )
            error.__cause__ = exc
            return _routing_failure(
                router_name=self.name,
                cell=cell,
                context=context,
                error=error,
                started_at=started_at,
                duration_ms=_duration_ms(started),
                route=route,
                cause=exc,
            )

        routed_trace = replace(
            outcome.trace,
            metadata={
                **outcome.trace.metadata,
                **_route_metadata(self.name, context.binding, route),
            },
        )
        try:
            validate_execution_trace_context(routed_trace, context)
        except ExecutionTraceMismatchError as exc:
            failed_trace = replace(
                routed_trace,
                status="failed",
                error=str(exc),
                metadata={
                    **routed_trace.metadata,
                    "route_status": "trace_rejected",
                    "delegate_status": outcome.trace.status,
                    "delegate_error": outcome.trace.error,
                },
            )
            return CellExecutionOutcome(
                trace=failed_trace,
                error=exc,
                prior_traces=outcome.prior_traces,
                control_record=outcome.control_record,
            )

        return CellExecutionOutcome(
            trace=routed_trace,
            result=outcome.result,
            error=outcome.error,
            prior_traces=outcome.prior_traces,
            control_record=outcome.control_record,
        )


def _routing_failure(
    *,
    router_name: str,
    cell: MarketCell,
    context: CellExecutionContext,
    error: Exception,
    started_at: str,
    duration_ms: float,
    route: ExecutorRoute | None = None,
    cause: Exception | None = None,
) -> CellExecutionOutcome:
    manifest = cell.manifest()
    binding = context.binding
    metadata = {
        "executor": router_name,
        "execution_phase": "routing" if route is None else "dispatch",
        "route_status": "failed",
        "planned_binding": binding is not None,
        "input_reference_ids": (
            list(context.node.input_reference_ids)
            if context.node is not None
            else []
        ),
        **cell_input_trace_metadata(context),
    }
    if binding is not None:
        metadata.update(_planned_binding_metadata(binding))
    if route is not None:
        metadata.update(_route_metadata(router_name, binding, route))
        metadata["route_status"] = "dispatch_failed"
    if cause is not None:
        metadata["cause_type"] = type(cause).__name__

    trace = CellRuntimeTrace(
        trace_id=context.trace_id,
        span_id=uuid4().hex,
        run_id=context.run_id,
        plan_id=context.plan_id,
        node_id=(
            context.node.node_id
            if context.node is not None
            else f"cell:{manifest.cell_id}"
        ),
        cell_id=manifest.cell_id,
        formula_version=manifest.formula_version,
        status="failed",
        started_at=started_at,
        finished_at=utc_now_iso(),
        duration_ms=duration_ms,
        error=str(error),
        metadata=metadata,
    )
    return CellExecutionOutcome(trace=trace, error=error)


def _planned_binding_metadata(binding: CellServiceBinding) -> dict[str, object]:
    return {
        "planned_binding_id": binding.binding_id,
        "planned_implementation_id": binding.implementation_id,
        "planned_service_id": binding.service_id,
        "planned_runtime": binding.runtime,
    }


def _route_metadata(
    router_name: str,
    binding: CellServiceBinding | None,
    route: ExecutorRoute,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "executor_router": router_name,
        "route_kind": route.kind,
        "route_key": route.key,
        "route_status": "dispatched",
        "routed_executor": route.executor.name,
    }
    if binding is not None:
        metadata.update(_planned_binding_metadata(binding))
    return metadata


def _validated_routes(
    routes: Mapping[str, CellExecutor],
    field_name: str,
) -> dict[str, CellExecutor]:
    normalized: dict[str, CellExecutor] = {}
    for key, executor in routes.items():
        normalized_key = str(key).strip()
        if not normalized_key:
            raise ValueError(f"executor route {field_name} must not be empty")
        if field_name == "runtime" and normalized_key not in get_args(CellRuntime):
            raise ValueError(f"unsupported executor route runtime: {normalized_key}")
        if normalized_key in normalized:
            raise ValueError(
                f"duplicate executor route {field_name}: {normalized_key}"
            )
        normalized[normalized_key] = executor
    return normalized


def _duration_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 6)
