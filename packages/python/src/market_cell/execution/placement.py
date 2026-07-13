from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import Any, Literal, Protocol

from market_cell.execution.models import CellRuntimeSummary, CellServiceBinding
from market_cell.models import CellManifest


CELL_PLACEMENT_DECISION_SCHEMA_VERSION = "cell_placement_decision.v1"

PlacementHistoryStatus = Literal[
    "no_history",
    "insufficient_history",
    "healthy",
    "unhealthy",
]


class PlacementUnavailableError(ValueError):
    pass


@dataclass(frozen=True)
class PlacementCandidateEvaluation:
    implementation_id: str
    service_id: str
    priority: int
    trace_count: int
    failure_rate: float | None
    p95_duration_ms: float | None
    history_status: PlacementHistoryStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "implementation_id": self.implementation_id,
            "service_id": self.service_id,
            "priority": self.priority,
            "trace_count": self.trace_count,
            "failure_rate": self.failure_rate,
            "p95_duration_ms": self.p95_duration_ms,
            "history_status": self.history_status,
        }


@dataclass(frozen=True)
class CellPlacementDecision:
    cell_id: str
    formula_version: str
    selected_binding: CellServiceBinding
    policy: str
    reason_codes: list[str]
    candidate_evaluations: list[PlacementCandidateEvaluation]
    schema_version: str = CELL_PLACEMENT_DECISION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "formula_version": self.formula_version,
            "selected_implementation_id": self.selected_binding.implementation_id,
            "selected_service_id": self.selected_binding.service_id,
            "policy": self.policy,
            "candidate_count": len(self.candidate_evaluations),
            "reason_codes": list(self.reason_codes),
            "candidate_evaluations": [
                evaluation.to_dict() for evaluation in self.candidate_evaluations
            ],
            "schema_version": self.schema_version,
        }


class CellPlacementPolicy(Protocol):
    @property
    def name(self) -> str:
        ...

    def select(
        self,
        manifest: CellManifest,
        candidates: list[CellServiceBinding],
        runtime_summaries: list[CellRuntimeSummary] | None = None,
    ) -> CellPlacementDecision:
        ...


class RuntimeAwarePlacementPolicy:
    def __init__(
        self,
        *,
        minimum_trace_count: int = 5,
        max_failure_rate: float = 0.2,
    ) -> None:
        if minimum_trace_count < 1:
            raise ValueError("minimum_trace_count must be at least 1")
        if not 0 <= max_failure_rate <= 1:
            raise ValueError("max_failure_rate must be between 0 and 1")
        self.minimum_trace_count = minimum_trace_count
        self.max_failure_rate = max_failure_rate

    @property
    def name(self) -> str:
        return "runtime_aware_priority_v0.1"

    def select(
        self,
        manifest: CellManifest,
        candidates: list[CellServiceBinding],
        runtime_summaries: list[CellRuntimeSummary] | None = None,
    ) -> CellPlacementDecision:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.cell_id == manifest.cell_id
            and candidate.formula_version == manifest.formula_version
        ]
        if not candidates:
            raise PlacementUnavailableError(
                f"no compatible implementation for {manifest.cell_id}@{manifest.formula_version}"
            )

        evaluations = [
            self._evaluate(candidate, runtime_summaries or [])
            for candidate in candidates
        ]
        non_unhealthy = [
            evaluation
            for evaluation in evaluations
            if evaluation.history_status != "unhealthy"
        ]
        selection_pool = non_unhealthy or evaluations
        selected_evaluation = min(selection_pool, key=_selection_rank)
        binding_by_key = {
            (binding.implementation_id, binding.service_id): binding
            for binding in candidates
        }
        selected_binding = binding_by_key[
            (selected_evaluation.implementation_id, selected_evaluation.service_id)
        ]

        return CellPlacementDecision(
            cell_id=manifest.cell_id,
            formula_version=manifest.formula_version,
            selected_binding=selected_binding,
            policy=self.name,
            reason_codes=_reason_codes(selected_evaluation, evaluations),
            candidate_evaluations=sorted(
                evaluations,
                key=lambda item: (item.priority, item.implementation_id, item.service_id),
            ),
        )

    def _evaluate(
        self,
        candidate: CellServiceBinding,
        runtime_summaries: list[CellRuntimeSummary],
    ) -> PlacementCandidateEvaluation:
        summaries = [
            summary
            for summary in runtime_summaries
            if summary.cell_id == candidate.cell_id
            and summary.formula_version == candidate.formula_version
            and summary.implementation_id == candidate.implementation_id
            and summary.service_id == candidate.service_id
            and summary.runtime == candidate.runtime
        ]
        trace_count = sum(summary.trace_count for summary in summaries)
        failed_count = sum(summary.failed_count for summary in summaries)
        failure_rate = (
            round(failed_count / trace_count, 6) if trace_count else None
        )
        p95_duration_ms = (
            max(summary.p95_duration_ms for summary in summaries)
            if summaries
            else None
        )

        if trace_count == 0:
            history_status: PlacementHistoryStatus = "no_history"
        elif trace_count < self.minimum_trace_count:
            history_status = "insufficient_history"
        elif failure_rate is not None and failure_rate > self.max_failure_rate:
            history_status = "unhealthy"
        else:
            history_status = "healthy"

        return PlacementCandidateEvaluation(
            implementation_id=candidate.implementation_id,
            service_id=candidate.service_id,
            priority=candidate.priority,
            trace_count=trace_count,
            failure_rate=failure_rate,
            p95_duration_ms=p95_duration_ms,
            history_status=history_status,
        )


def _selection_rank(evaluation: PlacementCandidateEvaluation) -> tuple[Any, ...]:
    p95_duration_ms = (
        evaluation.p95_duration_ms
        if evaluation.p95_duration_ms is not None
        else inf
    )
    if evaluation.history_status == "unhealthy":
        return (
            1,
            evaluation.failure_rate if evaluation.failure_rate is not None else 1.0,
            evaluation.priority,
            p95_duration_ms,
            evaluation.implementation_id,
            evaluation.service_id,
        )
    history_rank = {
        "healthy": 0,
        "insufficient_history": 1,
        "no_history": 2,
    }[evaluation.history_status]
    return (
        0,
        evaluation.priority,
        history_rank,
        p95_duration_ms,
        evaluation.implementation_id,
        evaluation.service_id,
    )


def _reason_codes(
    selected: PlacementCandidateEvaluation,
    evaluations: list[PlacementCandidateEvaluation],
) -> list[str]:
    reasons: list[str] = []
    if len(evaluations) == 1:
        reasons.append("only_compatible_candidate")
    if any(
        evaluation.history_status == "unhealthy"
        and (
            evaluation.implementation_id,
            evaluation.service_id,
        )
        != (
            selected.implementation_id,
            selected.service_id,
        )
        for evaluation in evaluations
    ):
        reasons.append("unhealthy_candidates_avoided")
    if all(evaluation.history_status == "unhealthy" for evaluation in evaluations):
        reasons.append("all_candidates_unhealthy")
    if selected.priority == min(evaluation.priority for evaluation in evaluations):
        reasons.append("selected_by_priority")
    if selected.history_status == "healthy":
        reasons.append("selected_with_healthy_runtime_history")
    elif selected.history_status == "insufficient_history":
        reasons.append("selected_with_insufficient_runtime_history")
    elif selected.history_status == "no_history":
        reasons.append("selected_without_runtime_history")
    else:
        reasons.append("selected_with_unhealthy_runtime_history")

    same_priority = [
        evaluation
        for evaluation in evaluations
        if evaluation.priority == selected.priority
        and evaluation.history_status == "healthy"
    ]
    if (
        len(same_priority) > 1
        and selected.p95_duration_ms is not None
        and selected.p95_duration_ms
        == min(
            evaluation.p95_duration_ms
            for evaluation in same_priority
            if evaluation.p95_duration_ms is not None
        )
    ):
        reasons.append("selected_by_runtime_latency")
    return reasons
