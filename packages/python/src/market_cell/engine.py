from copy import deepcopy
from dataclasses import replace
from typing import Any

from market_cell import __version__
from market_cell.events import EventBus
from market_cell.execution import CellExecutionPlan, build_local_execution_plan
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
                result = cell.analyze(request)
                child_results.append(result)
                self.event_bus.emit(
                    "cell.completed",
                    {
                        "run_id": run.run_id,
                        "cell_id": result.cell_id,
                        "score": result.score,
                        "direction": result.direction,
                    },
                )

            decision = self.registry.decision_cell.analyze(request, child_results)
            completed_run = run.complete(run.run_id)
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


def _merge_metadata(
    *items: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for item in items:
        payload.update(deepcopy(item or {}))
    return payload
