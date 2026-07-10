from copy import deepcopy
from dataclasses import replace
from time import perf_counter
from typing import Any
from uuid import uuid4

from market_cell import __version__
from market_cell.events import EventBus, utc_now_iso
from market_cell.execution import (
    CellExecutionPlan,
    CellRuntimeTrace,
    build_local_execution_plan,
    summarize_runtime_traces,
)
from market_cell.cells.base import MarketCell
from market_cell.models import AnalysisReport, AnalysisRequest, CellResult
from market_cell.reports import ReportStore
from market_cell.registry import CellRegistry, default_registry
from market_cell.runs import AnalysisRun
from market_cell.validation import validate_request


class AnalysisEngine:
    def __init__(
        self,
        registry: CellRegistry | None = None,
        event_bus: EventBus | None = None,
        report_store: ReportStore | None = None,
        run_metadata: dict[str, Any] | None = None,
        include_execution_plan: bool = True,
    ) -> None:
        self.registry = registry or default_registry()
        self.event_bus = event_bus or EventBus()
        self.report_store = report_store
        self.run_metadata = dict(run_metadata or {})
        self.include_execution_plan = include_execution_plan

    def run(
        self,
        request: AnalysisRequest,
        metadata: dict[str, Any] | None = None,
    ) -> AnalysisReport:
        validate_request(request)
        execution_plan = self._execution_plan(request) if self.include_execution_plan else None
        trace_id = uuid4().hex
        runtime_traces: list[CellRuntimeTrace] = []
        run = AnalysisRun.start(
            request,
            self.registry.manifests(),
            metadata=_merge_metadata(
                self.run_metadata,
                execution_plan.to_run_metadata() if execution_plan is not None else None,
                metadata,
            ),
        )
        self.event_bus.emit(
            "analysis.started",
            {"run_id": run.run_id, "target": request.target, "horizon": request.horizon},
        )

        try:
            child_results: list[CellResult] = []
            for cell in self.registry.leaf_cells:
                result = self._analyze_with_trace(
                    cell=cell,
                    request=request,
                    run_id=run.run_id,
                    trace_id=trace_id,
                    runtime_traces=runtime_traces,
                    execution_plan=execution_plan,
                )
                child_results.append(result)
                self.event_bus.emit(
                    "cell.completed",
                    {
                        "run_id": run.run_id,
                        "cell_id": result.cell_id,
                        "score": result.score,
                        "direction": result.direction,
                        "duration_ms": runtime_traces[-1].duration_ms if runtime_traces else None,
                    },
                )

            decision = self._analyze_with_trace(
                cell=self.registry.decision_cell,
                request=request,
                run_id=run.run_id,
                trace_id=trace_id,
                runtime_traces=runtime_traces,
                execution_plan=execution_plan,
                child_results=child_results,
            )
            completed_run = run.with_metadata(
                {
                    "cell_runtime_traces": [trace.to_dict() for trace in runtime_traces],
                    "cell_runtime_summaries": [
                        summary.to_dict() for summary in summarize_runtime_traces(runtime_traces)
                    ],
                }
            ).complete(run.run_id)
            report = AnalysisReport(
                target=request.target,
                horizon=request.horizon,
                decision=decision,
                summary=decision.explanation,
                run_id=run.run_id,
                report_id=completed_run.report_id,
                engine_version=__version__,
                formula_versions=run.formula_versions,
                created_at=completed_run.finished_at,
            )

            if self.report_store is not None:
                report_id = self.report_store.save(report, completed_run)
                report = replace(report, report_id=report_id)
                self.event_bus.emit("analysis.saved", {"run_id": run.run_id, "report_id": report_id})

            self.event_bus.emit("analysis.completed", {"run_id": run.run_id, "report_id": report.report_id})
            return report
        except Exception as exc:
            failed_run = run.fail(str(exc))
            self.event_bus.emit(
                "analysis.failed",
                {"run_id": failed_run.run_id, "target": request.target, "error": failed_run.error},
            )
            raise

    def _execution_plan(self, request: AnalysisRequest) -> CellExecutionPlan:
        return build_local_execution_plan(self.registry, request)

    def _analyze_with_trace(
        self,
        cell: MarketCell,
        request: AnalysisRequest,
        run_id: str,
        trace_id: str,
        runtime_traces: list[CellRuntimeTrace],
        execution_plan: CellExecutionPlan | None,
        child_results: list[CellResult] | None = None,
    ) -> CellResult:
        node = _node_for_cell(execution_plan, cell.cell_id)
        binding = _binding_for_cell(execution_plan, cell.cell_id)
        started_at = utc_now_iso()
        started = perf_counter()
        try:
            result = cell.analyze(request, child_results)
        except Exception as exc:
            finished_at = utc_now_iso()
            runtime_traces.append(
                _runtime_trace(
                    trace_id=trace_id,
                    run_id=run_id,
                    cell=cell,
                    status="failed",
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=_duration_ms(started),
                    node=node,
                    binding=binding,
                    execution_plan=execution_plan,
                    error=str(exc),
                )
            )
            raise

        finished_at = utc_now_iso()
        runtime_traces.append(
            _runtime_trace(
                trace_id=trace_id,
                run_id=run_id,
                cell=cell,
                status="succeeded",
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=_duration_ms(started),
                node=node,
                binding=binding,
                execution_plan=execution_plan,
            )
        )
        return result


def _merge_metadata(
    *items: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for item in items:
        payload.update(deepcopy(item or {}))
    return payload


def _runtime_trace(
    trace_id: str,
    run_id: str,
    cell: MarketCell,
    status: str,
    started_at: str,
    finished_at: str,
    duration_ms: float,
    node,
    binding,
    execution_plan: CellExecutionPlan | None,
    error: str | None = None,
) -> CellRuntimeTrace:
    manifest = cell.manifest()
    return CellRuntimeTrace(
        trace_id=trace_id,
        span_id=uuid4().hex,
        run_id=run_id,
        plan_id=execution_plan.plan_id if execution_plan is not None else None,
        node_id=node.node_id if node is not None else f"cell:{cell.cell_id}",
        cell_id=cell.cell_id,
        implementation_id=node.implementation_id if node is not None else None,
        service_id=binding.service_id if binding is not None else None,
        runtime=binding.runtime if binding is not None else None,
        formula_version=manifest.formula_version,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        error=error,
    )


def _duration_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 6)


def _node_for_cell(execution_plan: CellExecutionPlan | None, cell_id: str):
    if execution_plan is None:
        return None
    for node in execution_plan.nodes:
        if node.cell_id == cell_id:
            return node
    return None


def _binding_for_cell(execution_plan: CellExecutionPlan | None, cell_id: str):
    if execution_plan is None:
        return None
    for binding in execution_plan.service_bindings:
        if binding.cell_id == cell_id:
            return binding
    return None
