from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import Any, Literal, Protocol

from market_cell.execution.models import CellServiceBinding
from market_cell.execution.runtime_store import RuntimeSummarySnapshot
from market_cell.models import CellManifest


CELL_PLACEMENT_DECISION_SCHEMA_VERSION = "cell_placement_decision.v3"

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
    binding_id: str
    implementation_id: str
    service_id: str
    priority: int
    trace_count: int
    failure_rate: float | None
    p95_duration_ms: float | None
    history_status: PlacementHistoryStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
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
    fallback_bindings: list[CellServiceBinding]
    policy: str
    reason_codes: list[str]
    candidate_evaluations: list[PlacementCandidateEvaluation]
    schema_version: str = CELL_PLACEMENT_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        bindings = [self.selected_binding, *self.fallback_bindings]
        binding_ids = [binding.binding_id for binding in bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("placement decision bindings must be unique")
        if any(
            binding.cell_id != self.cell_id
            or binding.formula_version != self.formula_version
            for binding in bindings
        ):
            raise ValueError("placement decision binding is incompatible with the Cell")
        if not self.candidate_evaluations:
            raise ValueError("placement decision requires candidate evaluations")
        evaluation_binding_ids = [
            evaluation.binding_id for evaluation in self.candidate_evaluations
        ]
        if len(evaluation_binding_ids) != len(set(evaluation_binding_ids)):
            raise ValueError("placement candidate evaluations must be unique")
        if any(binding_id not in evaluation_binding_ids for binding_id in binding_ids):
            raise ValueError("placement binding is missing from candidate evaluations")

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "formula_version": self.formula_version,
            "selected_binding_id": self.selected_binding.binding_id,
            "selected_implementation_id": self.selected_binding.implementation_id,
            "selected_service_id": self.selected_binding.service_id,
            "fallback_binding_ids": [
                binding.binding_id for binding in self.fallback_bindings
            ],
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
        runtime_summary_snapshot: RuntimeSummarySnapshot | None = None,
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
        return "runtime_aware_priority_v0.2"

    def select(
        self,
        manifest: CellManifest,
        candidates: list[CellServiceBinding],
        runtime_summary_snapshot: RuntimeSummarySnapshot | None = None,
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
            self._evaluate(candidate, runtime_summary_snapshot)
            for candidate in candidates
        ]
        non_unhealthy = [
            evaluation
            for evaluation in evaluations
            if evaluation.history_status != "unhealthy"
        ]
        selection_pool = non_unhealthy or evaluations
        ranked_selection_pool = sorted(selection_pool, key=_selection_rank)
        selected_evaluation = ranked_selection_pool[0]
        binding_by_id = {binding.binding_id: binding for binding in candidates}
        selected_binding = binding_by_id[selected_evaluation.binding_id]
        fallback_bindings = [
            binding_by_id[evaluation.binding_id]
            for evaluation in ranked_selection_pool[1:]
        ]

        return CellPlacementDecision(
            cell_id=manifest.cell_id,
            formula_version=manifest.formula_version,
            selected_binding=selected_binding,
            fallback_bindings=fallback_bindings,
            policy=self.name,
            reason_codes=_reason_codes(selected_evaluation, evaluations),
            candidate_evaluations=sorted(
                evaluations,
                key=_selection_rank,
            ),
        )

    def _evaluate(
        self,
        candidate: CellServiceBinding,
        runtime_summary_snapshot: RuntimeSummarySnapshot | None,
    ) -> PlacementCandidateEvaluation:
        history = next(
            (
                entry
                for entry in (
                    runtime_summary_snapshot.entries
                    if runtime_summary_snapshot is not None
                    else []
                )
                if entry.cell_id == candidate.cell_id
                and entry.formula_version == candidate.formula_version
                and entry.implementation_id == candidate.implementation_id
                and entry.service_id == candidate.service_id
                and entry.runtime == candidate.runtime
            ),
            None,
        )
        trace_count = history.trace_count if history is not None else 0
        failure_rate = history.failure_rate if history is not None else None
        p95_duration_ms = history.p95_duration_ms if history is not None else None

        if trace_count == 0:
            history_status: PlacementHistoryStatus = "no_history"
        elif trace_count < self.minimum_trace_count:
            history_status = "insufficient_history"
        elif failure_rate is not None and failure_rate > self.max_failure_rate:
            history_status = "unhealthy"
        else:
            history_status = "healthy"

        return PlacementCandidateEvaluation(
            binding_id=candidate.binding_id,
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
    if any(
        evaluation.binding_id != selected.binding_id
        and (
            evaluation.history_status != "unhealthy"
            or all(item.history_status == "unhealthy" for item in evaluations)
        )
        for evaluation in evaluations
    ):
        reasons.append("fallback_candidates_available")
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
