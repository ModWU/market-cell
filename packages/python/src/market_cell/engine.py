from copy import deepcopy
from dataclasses import replace
from typing import Any
from uuid import uuid4

from market_cell import __version__
from market_cell.events import EventBus
from market_cell.execution import (
    CellExecutionContext,
    CellExecutionPlan,
    CellExecutor,
    CellRuntimeTrace,
    ExecutionPlanValidationError,
    LocalCellExecutor,
    build_local_execution_plan,
    summarize_runtime_traces,
    validate_cell_result,
    validate_execution_plan,
    validate_execution_trace,
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
        executor: CellExecutor | None = None,
    ) -> None:
        self.registry = registry or default_registry()
        self.event_bus = event_bus or EventBus()
        self.report_store = report_store
        self.run_metadata = dict(run_metadata or {})
        self.include_execution_plan = include_execution_plan
        self.executor = executor or LocalCellExecutor()

    def run(
        self,
        request: AnalysisRequest,
        metadata: dict[str, Any] | None = None,
    ) -> AnalysisReport:
        validate_request(request)
        trace_id = uuid4().hex
        runtime_traces: list[CellRuntimeTrace] = []
        run = AnalysisRun.start(
            request,
            self.registry.manifests(),
            metadata=_merge_metadata(self.run_metadata, metadata),
        )
        self.event_bus.emit(
            "analysis.started",
            {"run_id": run.run_id, "target": request.target, "horizon": request.horizon},
        )

        execution_plan: CellExecutionPlan | None = None
        try:
            if self.include_execution_plan:
                execution_plan = self._execution_plan(request)
                run = run.with_metadata(execution_plan.to_run_metadata())
                validate_execution_plan(execution_plan)
            child_results: list[CellResult] = []
            for cell in self.registry.leaf_cells:
                result = self._execute_cell(
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

            decision = self._execute_cell(
                cell=self.registry.decision_cell,
                request=request,
                run_id=run.run_id,
                trace_id=trace_id,
                runtime_traces=runtime_traces,
                execution_plan=execution_plan,
                child_results=child_results,
            )
            completed_run = run.with_metadata(_runtime_metadata(runtime_traces)).complete(run.run_id)
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
            if isinstance(exc, ExecutionPlanValidationError):
                if "cell_execution_plan" not in run.metadata:
                    run = run.with_metadata(exc.plan.to_run_metadata())
                run = run.with_metadata({"execution_plan_validation": exc.to_dict()})
            failed_run = run.with_metadata(_runtime_metadata(runtime_traces)).fail(str(exc))
            persistence_error = _save_failed_run(self.report_store, failed_run)
            self.event_bus.emit(
                "analysis.failed",
                {
                    "run_id": failed_run.run_id,
                    "target": request.target,
                    "error": failed_run.error,
                    "persistence_error": persistence_error,
                },
            )
            raise

    def _execution_plan(self, request: AnalysisRequest) -> CellExecutionPlan:
        service_id = (
            self.executor.service_id
            if isinstance(self.executor, LocalCellExecutor)
            else "python-local"
        )
        return build_local_execution_plan(self.registry, request, service_id)

    def _execute_cell(
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
        outcome = self.executor.execute(
            cell=cell,
            request=request,
            child_results=child_results,
            context=CellExecutionContext(
                run_id=run_id,
                trace_id=trace_id,
                plan_id=execution_plan.plan_id if execution_plan is not None else None,
                node=node,
                binding=_binding_for_node(execution_plan, node),
            ),
        )
        runtime_traces.append(outcome.trace)
        result = outcome.unwrap()
        validate_execution_trace(outcome.trace, execution_plan)
        validate_cell_result(cell, request, result)
        return result


def _merge_metadata(
    *items: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for item in items:
        payload.update(deepcopy(item or {}))
    return payload


def _runtime_metadata(runtime_traces: list[CellRuntimeTrace]) -> dict[str, Any]:
    return {
        "cell_runtime_traces": [trace.to_dict() for trace in runtime_traces],
        "cell_runtime_summaries": [
            summary.to_dict() for summary in summarize_runtime_traces(runtime_traces)
        ],
    }


def _save_failed_run(
    report_store: ReportStore | None,
    failed_run: AnalysisRun,
) -> str | None:
    if report_store is None:
        return None
    try:
        report_store.save_run(failed_run)
    except Exception as exc:
        return str(exc)
    return None


def _node_for_cell(execution_plan: CellExecutionPlan | None, cell_id: str):
    if execution_plan is None:
        return None
    for node in execution_plan.nodes:
        if node.cell_id == cell_id:
            return node
    return None


def _binding_for_node(execution_plan: CellExecutionPlan | None, node):
    if execution_plan is None or node is None:
        return None
    for binding in execution_plan.service_bindings:
        if binding.binding_id == node.binding_id:
            return binding
    return None
