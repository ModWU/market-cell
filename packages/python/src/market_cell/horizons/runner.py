from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Sequence
from uuid import uuid4

from market_cell.engine import AnalysisEngine
from market_cell.events import utc_now_iso
from market_cell.execution import CancellationSignal
from market_cell.hashing import stable_json_hash
from market_cell.horizons.models import (
    MultiHorizonAnalysis,
    MultiHorizonRequest,
)
from market_cell.horizons.validation import validate_multi_horizon_request
from market_cell.inputs import InputCompositionError, InputSnapshot
from market_cell.models import AnalysisReport, AnalysisRequest


MULTI_HORIZON_EXECUTION_ERROR_SCHEMA_VERSION = (
    "multi_horizon_execution_error.v1"
)

MultiHorizonExecutionCode = Literal[
    "engine_factory_failure",
    "graph_mismatch",
    "formula_version_mismatch",
    "analysis_failure",
    "report_scope_mismatch",
    "report_formula_mismatch",
]

EngineFactory = Callable[[AnalysisRequest], AnalysisEngine]


class MultiHorizonExecutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: MultiHorizonExecutionCode,
        batch_id: str,
        request: MultiHorizonRequest,
        failed_horizon: str | None,
        completed_reports: Sequence[AnalysisReport] = (),
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.batch_id = batch_id
        self.request_id = request.request_id
        self.request_hash = request.content_hash
        self.target = request.target
        self.as_of_ms = request.as_of_ms
        self.horizon_order = request.horizon_order
        self.failed_horizon = failed_horizon
        self.completed_reports = tuple(completed_reports)
        self.cause = cause
        self.schema_version = MULTI_HORIZON_EXECUTION_ERROR_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": "multi_horizon_execution",
            "code": self.code,
            "batch_id": self.batch_id,
            "request_id": self.request_id,
            "request_hash": self.request_hash,
            "target": self.target,
            "as_of_ms": self.as_of_ms,
            "horizon_order": list(self.horizon_order),
            "completed_horizons": [
                report.horizon for report in self.completed_reports
            ],
            "failed_horizon": self.failed_horizon,
            "error": str(self),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class _PreparedHorizon:
    request: AnalysisRequest
    engine: AnalysisEngine
    graph_id: str
    graph_version: str
    graph_content_hash: str
    formula_versions: dict[str, str]


class MultiHorizonAnalyzer:
    """Run validated horizons independently without inventing an aggregate view."""

    def __init__(self, engine_factory: EngineFactory | None = None) -> None:
        self.engine_factory = engine_factory or (lambda _: AnalysisEngine())

    def run(
        self,
        request: MultiHorizonRequest,
        metadata: dict[str, Any] | None = None,
        *,
        cancellation_signal: CancellationSignal | None = None,
        input_snapshots_by_horizon: Mapping[
            str,
            Sequence[InputSnapshot],
        ]
        | None = None,
    ) -> MultiHorizonAnalysis:
        validate_multi_horizon_request(request)
        child_metadata = deepcopy(metadata or {})
        if "multi_horizon" in child_metadata:
            raise ValueError(
                "metadata.multi_horizon is reserved for batch audit data"
            )
        horizon_inputs = _validate_horizon_inputs(
            request,
            input_snapshots_by_horizon,
        )
        batch_id = f"multi-horizon:{uuid4().hex}"
        prepared = self._prepare(request, batch_id=batch_id)
        expected = prepared[0]
        completed_reports: list[AnalysisReport] = []

        for index, item in enumerate(prepared):
            horizon = item.request.horizon
            audit = {
                "schema_version": request.schema_version,
                "batch_id": batch_id,
                "request_id": request.request_id,
                "request_hash": request.content_hash,
                "target": request.target,
                "as_of_ms": request.as_of_ms,
                "horizon_order": request.horizon_order,
                "horizon_index": index,
                "horizon_count": len(prepared),
                "execution_mode": "sequential",
                "failure_mode": "fail_fast",
                "aggregation_status": "not_computed",
                "request_metadata": deepcopy(request.metadata),
            }
            try:
                report = item.engine.run(
                    item.request,
                    metadata={
                        **deepcopy(child_metadata),
                        "multi_horizon": audit,
                    },
                    cancellation_signal=cancellation_signal,
                    input_snapshots=list(horizon_inputs.get(horizon, ())),
                )
            except Exception as exc:
                raise MultiHorizonExecutionError(
                    f"multi-horizon analysis failed at {horizon}: {exc}",
                    code="analysis_failure",
                    batch_id=batch_id,
                    request=request,
                    failed_horizon=horizon,
                    completed_reports=completed_reports,
                    cause=exc,
                ) from exc
            if (
                report.target != request.target
                or report.horizon != horizon
                or report.decision.target != report.target
                or report.decision.horizon != report.horizon
            ):
                raise MultiHorizonExecutionError(
                    "multi-horizon child report scope does not match its request",
                    code="report_scope_mismatch",
                    batch_id=batch_id,
                    request=request,
                    failed_horizon=horizon,
                    completed_reports=completed_reports,
                )
            if report.formula_versions != expected.formula_versions:
                raise MultiHorizonExecutionError(
                    "multi-horizon child report formula versions drifted "
                    "inside one batch",
                    code="report_formula_mismatch",
                    batch_id=batch_id,
                    request=request,
                    failed_horizon=horizon,
                    completed_reports=completed_reports,
                )
            completed_reports.append(report)

        return MultiHorizonAnalysis(
            batch_id=batch_id,
            request_id=request.request_id,
            request_hash=request.content_hash,
            target=request.target,
            as_of_ms=request.as_of_ms,
            horizon_order=request.horizon_order,
            reports=completed_reports,
            graph_id=expected.graph_id,
            graph_version=expected.graph_version,
            graph_content_hash=expected.graph_content_hash,
            formula_versions=dict(expected.formula_versions),
            created_at=utc_now_iso(),
            metadata={
                "execution_mode": "sequential",
                "failure_mode": "fail_fast",
                "request_metadata": deepcopy(request.metadata),
            },
        )

    def _prepare(
        self,
        request: MultiHorizonRequest,
        *,
        batch_id: str,
    ) -> list[_PreparedHorizon]:
        prepared: list[_PreparedHorizon] = []
        expected: _PreparedHorizon | None = None
        for child in request.requests:
            try:
                engine = self.engine_factory(child)
            except Exception as exc:
                raise MultiHorizonExecutionError(
                    f"could not create analysis engine for {child.horizon}: {exc}",
                    code="engine_factory_failure",
                    batch_id=batch_id,
                    request=request,
                    failed_horizon=child.horizon,
                    cause=exc,
                ) from exc
            if not isinstance(engine, AnalysisEngine):
                error = TypeError(
                    "multi-horizon engine factory must return AnalysisEngine"
                )
                raise MultiHorizonExecutionError(
                    str(error),
                    code="engine_factory_failure",
                    batch_id=batch_id,
                    request=request,
                    failed_horizon=child.horizon,
                    cause=error,
                ) from error
            graph = engine.graph_definition
            graph_content_hash = stable_json_hash(graph.to_dict())
            formula_versions = _engine_formula_versions(engine)
            item = _PreparedHorizon(
                request=child,
                engine=engine,
                graph_id=graph.graph_id,
                graph_version=graph.graph_version,
                graph_content_hash=graph_content_hash,
                formula_versions=formula_versions,
            )
            if expected is None:
                expected = item
            elif (
                item.graph_id,
                item.graph_version,
                item.graph_content_hash,
            ) != (
                expected.graph_id,
                expected.graph_version,
                expected.graph_content_hash,
            ):
                raise MultiHorizonExecutionError(
                    "all horizons must use the same graph identity and content",
                    code="graph_mismatch",
                    batch_id=batch_id,
                    request=request,
                    failed_horizon=child.horizon,
                )
            elif item.formula_versions != expected.formula_versions:
                raise MultiHorizonExecutionError(
                    "all horizons must use the same Cell formula versions",
                    code="formula_version_mismatch",
                    batch_id=batch_id,
                    request=request,
                    failed_horizon=child.horizon,
                )
            prepared.append(item)
        return prepared


def _engine_formula_versions(engine: AnalysisEngine) -> dict[str, str]:
    graph_cell_ids = {node.cell_id for node in engine.graph_definition.nodes}
    return {
        manifest.cell_id: manifest.formula_version
        for manifest in engine.registry.manifests()
        if manifest.cell_id in graph_cell_ids
    }


def _validate_horizon_inputs(
    request: MultiHorizonRequest,
    inputs: Mapping[str, Sequence[InputSnapshot]] | None,
) -> dict[str, tuple[InputSnapshot, ...]]:
    if inputs is None:
        return {}
    horizon_names = set(request.horizon_order)
    unknown = sorted(set(inputs) - horizon_names)
    if unknown:
        raise InputCompositionError(
            "multi-horizon extra inputs reference unknown horizons: "
            + ", ".join(unknown)
        )
    normalized: dict[str, tuple[InputSnapshot, ...]] = {}
    for horizon, snapshots in inputs.items():
        values = tuple(snapshots)
        if any(not isinstance(item, InputSnapshot) for item in values):
            raise InputCompositionError(
                f"multi-horizon inputs for {horizon} must be InputSnapshot instances"
            )
        normalized[horizon] = values
    return normalized
