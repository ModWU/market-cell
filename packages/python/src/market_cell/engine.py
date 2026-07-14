from copy import deepcopy
from dataclasses import replace
from typing import Any
from uuid import uuid4

from market_cell import __version__
from market_cell.events import EventBus
from market_cell.execution import (
    CellExecutionCoordinator,
    CellExecutionPlan,
    CellExecutor,
    CellRuntimeTrace,
    ExecutionPlanValidationError,
    LocalCellExecutor,
    NodeExecutionCompletion,
    PlanDrivenLocalCoordinator,
    PlanExecutionOutcome,
    build_local_execution_plan,
    summarize_runtime_traces,
    validate_execution_plan,
)
from market_cell.models import AnalysisReport, AnalysisRequest
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
        coordinator: CellExecutionCoordinator | None = None,
    ) -> None:
        if not include_execution_plan:
            raise ValueError(
                "ExecutionPlan is mandatory; plan-free execution is no longer supported"
            )
        self.registry = registry or default_registry()
        self.event_bus = event_bus or EventBus()
        self.report_store = report_store
        self.run_metadata = dict(run_metadata or {})
        self.executor = executor or LocalCellExecutor()
        self.coordinator = coordinator or PlanDrivenLocalCoordinator()

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
        execution_outcome: PlanExecutionOutcome | None = None
        try:
            execution_plan = self._execution_plan(request)
            run = run.with_metadata(execution_plan.to_run_metadata())
            validated_plan = validate_execution_plan(execution_plan)
            execution_outcome = self.coordinator.execute(
                validated_plan=validated_plan,
                registry=self.registry,
                executor=self.executor,
                request=request,
                run_id=run.run_id,
                trace_id=trace_id,
                on_node_completed=lambda completion: self._emit_node_completion(
                    run.run_id,
                    completion,
                ),
            )
            runtime_traces.extend(execution_outcome.runtime_traces)
            run = run.with_metadata(execution_outcome.to_run_metadata())
            decision = execution_outcome.unwrap()
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
                    "failed_node_id": (
                        execution_outcome.failed_node_id
                        if execution_outcome is not None
                        else None
                    ),
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

    def _emit_node_completion(
        self,
        run_id: str,
        completion: NodeExecutionCompletion,
    ) -> None:
        payload = {
            "run_id": run_id,
            "node_id": completion.node_id,
            "cell_id": completion.cell_id,
            "binding_id": completion.binding_id,
            "execution_role": completion.execution_role,
            "duration_ms": (
                completion.trace.duration_ms if completion.trace is not None else None
            ),
        }
        if completion.result is None:
            self.event_bus.emit(
                "cell.failed",
                {
                    **payload,
                    "error": (
                        str(completion.error)
                        if completion.error is not None
                        else "unknown cell execution failure"
                    ),
                },
            )
            return
        self.event_bus.emit(
            "cell.completed",
            {
                **payload,
                "score": completion.result.score,
                "direction": completion.result.direction,
            },
        )


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
