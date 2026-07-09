from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from market_cell.engine import AnalysisEngine
from market_cell.models import AnalysisRequest
from market_cell.reports import ReportStore
from market_cell.runs import stable_json_hash


@dataclass(frozen=True)
class ReplayComparison:
    report_id: str
    original_run_id: str | None
    replay_run_id: str | None
    target: str
    horizon: str
    input_hash_matches: bool
    result_stable: bool
    drift_fields: list[str]
    score_delta: float
    formula_version_changes: dict[str, dict[str, str | None]]
    original_decision: dict[str, Any]
    replayed_decision: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReplayRunner:
    def __init__(
        self,
        store: ReportStore,
        engine_factory: Callable[[], AnalysisEngine] | None = None,
        score_tolerance: float = 1e-9,
    ) -> None:
        self.store = store
        self.engine_factory = engine_factory or AnalysisEngine
        self.score_tolerance = score_tolerance

    def replay(self, report_id: str) -> ReplayComparison:
        original_report = self.store.load_report(report_id)
        original_run_id = original_report.get("run_id") or report_id
        original_run = self.store.load_run(original_run_id)
        input_snapshot = dict(original_run["input_snapshot"])

        request = AnalysisRequest.from_dict(input_snapshot)
        replayed_report = self.engine_factory().run(request)

        original_decision = _decision_summary(original_report["decision"])
        replayed_decision = _decision_summary(replayed_report.decision.to_dict())
        drift_fields = _decision_drift_fields(original_decision, replayed_decision, self.score_tolerance)
        old_formula_versions = dict(original_run.get("formula_versions") or original_report.get("formula_versions") or {})
        formula_changes = compare_formula_versions(old_formula_versions, replayed_report.formula_versions)

        return ReplayComparison(
            report_id=report_id,
            original_run_id=original_run_id,
            replay_run_id=replayed_report.run_id,
            target=original_report["target"],
            horizon=original_report["horizon"],
            input_hash_matches=stable_json_hash(input_snapshot) == original_run.get("input_hash"),
            result_stable=not drift_fields,
            drift_fields=drift_fields,
            score_delta=replayed_decision["score"] - original_decision["score"],
            formula_version_changes=formula_changes,
            original_decision=original_decision,
            replayed_decision=replayed_decision,
        )


def compare_formula_versions(
    old_versions: dict[str, str],
    new_versions: dict[str, str],
) -> dict[str, dict[str, str | None]]:
    changes: dict[str, dict[str, str | None]] = {}
    for cell_id in sorted(set(old_versions) | set(new_versions)):
        old_value = old_versions.get(cell_id)
        new_value = new_versions.get(cell_id)
        if old_value != new_value:
            changes[cell_id] = {"old": old_value, "new": new_value}
    return changes


def _decision_summary(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "cell_id": decision.get("cell_id"),
        "direction": decision.get("direction"),
        "score": float(decision.get("score", 0)),
        "strength": float(decision.get("strength", 0)),
        "confidence": float(decision.get("confidence", 0)),
        "risk_level": decision.get("risk_level"),
        "action_posture": decision.get("action_posture"),
    }


def _decision_drift_fields(
    original: dict[str, Any],
    replayed: dict[str, Any],
    score_tolerance: float,
) -> list[str]:
    fields = ["direction", "risk_level", "action_posture", "strength", "confidence"]
    drift = [field for field in fields if original[field] != replayed[field]]
    if abs(replayed["score"] - original["score"]) > score_tolerance:
        drift.append("score")
    return drift
