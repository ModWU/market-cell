from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from market_cell.engine import AnalysisEngine
from market_cell.hashing import stable_json_hash
from market_cell.inputs import InputSnapshot
from market_cell.models import AnalysisRequest
from market_cell.reports import ReportStore


MAX_DECISION_TREE_DRIFT_PATHS = 100
REPLAY_COMPARISON_SCHEMA_VERSION = "replay_comparison.v1"


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
    decision_tree_stable: bool
    decision_tree_drift_paths: list[str]
    original_decision_tree_hash: str
    replayed_decision_tree_hash: str
    score_delta: float
    formula_version_changes: dict[str, dict[str, str | None]]
    graph_definition_changes: dict[str, dict[str, str | None]]
    original_decision: dict[str, Any]
    replayed_decision: dict[str, Any]
    schema_version: str = REPLAY_COMPARISON_SCHEMA_VERSION

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
        request, extra_inputs, input_hash_matches = _replay_inputs(original_run)
        engine = self.engine_factory()
        replayed_report = engine.run(request, input_snapshots=extra_inputs)

        original_decision_tree = dict(original_report["decision"])
        replayed_decision_tree = replayed_report.decision.to_dict()
        original_decision = _decision_summary(original_decision_tree)
        replayed_decision = _decision_summary(replayed_decision_tree)
        drift_fields = _decision_drift_fields(
            original_decision,
            replayed_decision,
            self.score_tolerance,
        )
        decision_tree_drift_paths = compare_decision_trees(
            original_decision_tree,
            replayed_decision_tree,
            numeric_tolerance=self.score_tolerance,
        )
        if decision_tree_drift_paths:
            drift_fields.append("decision_tree")
        old_formula_versions = dict(
            original_run.get("formula_versions")
            or original_report.get("formula_versions")
            or {}
        )
        formula_changes = compare_formula_versions(
            old_formula_versions,
            replayed_report.formula_versions,
        )
        original_graph = dict(
            (original_run.get("metadata") or {}).get("cell_graph_definition") or {}
        )
        graph_changes = compare_graph_definitions(
            original_graph,
            engine.graph_definition.to_dict(),
        )

        return ReplayComparison(
            report_id=report_id,
            original_run_id=original_run_id,
            replay_run_id=replayed_report.run_id,
            target=original_report["target"],
            horizon=original_report["horizon"],
            input_hash_matches=input_hash_matches,
            result_stable=not drift_fields,
            drift_fields=drift_fields,
            decision_tree_stable=not decision_tree_drift_paths,
            decision_tree_drift_paths=decision_tree_drift_paths,
            original_decision_tree_hash=stable_json_hash(
                original_decision_tree
            ),
            replayed_decision_tree_hash=stable_json_hash(
                replayed_decision_tree
            ),
            score_delta=replayed_decision["score"] - original_decision["score"],
            formula_version_changes=formula_changes,
            graph_definition_changes=graph_changes,
            original_decision=original_decision,
            replayed_decision=replayed_decision,
        )


def _replay_inputs(
    original_run: dict[str, Any],
) -> tuple[AnalysisRequest, list[InputSnapshot], bool]:
    serialized_inputs = original_run.get("input_snapshots")
    if isinstance(serialized_inputs, list):
        snapshots = [
            InputSnapshot.from_dict(dict(item)) for item in serialized_inputs
        ]
        request_inputs = [
            item for item in snapshots if item.input_kind == "analysis_request"
        ]
        if len(request_inputs) != 1:
            raise ValueError(
                "analysis_run.v2 replay requires exactly one analysis_request snapshot"
            )
        request_input = request_inputs[0]
        request = request_input.to_analysis_request()
        return (
            request,
            [
                item
                for item in snapshots
                if item.input_kind != "analysis_request"
            ],
            stable_json_hash(request_input.payload)
            == original_run.get("input_hash"),
        )

    legacy_input = dict(original_run["input_snapshot"])
    return (
        AnalysisRequest.from_dict(legacy_input),
        [],
        stable_json_hash(legacy_input) == original_run.get("input_hash"),
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


def compare_graph_definitions(
    old_graph: dict[str, Any],
    new_graph: dict[str, Any],
) -> dict[str, dict[str, str | None]]:
    changes: dict[str, dict[str, str | None]] = {}
    for field_name in ("graph_id", "graph_version", "schema_version"):
        old_value = old_graph.get(field_name)
        new_value = new_graph.get(field_name)
        if old_value != new_value:
            changes[field_name] = {"old": old_value, "new": new_value}
    if old_graph and new_graph:
        identity_fields = {"graph_id", "graph_version", "schema_version"}
        old_content = {
            key: value for key, value in old_graph.items() if key not in identity_fields
        }
        new_content = {
            key: value for key, value in new_graph.items() if key not in identity_fields
        }
        old_hash = stable_json_hash(old_content)
        new_hash = stable_json_hash(new_content)
        if old_hash != new_hash:
            changes["content_hash"] = {"old": old_hash, "new": new_hash}
    return changes


def compare_decision_trees(
    original: dict[str, Any],
    replayed: dict[str, Any],
    *,
    numeric_tolerance: float = 1e-9,
) -> list[str]:
    """Return bounded field paths whose full decision-tree values drifted."""
    if numeric_tolerance < 0:
        raise ValueError("decision tree numeric tolerance must not be negative")
    paths: list[str] = []
    _collect_value_drift_paths(
        original,
        replayed,
        path="decision",
        numeric_tolerance=numeric_tolerance,
        paths=paths,
    )
    return paths


def _collect_value_drift_paths(
    original: Any,
    replayed: Any,
    *,
    path: str,
    numeric_tolerance: float,
    paths: list[str],
) -> None:
    if len(paths) >= MAX_DECISION_TREE_DRIFT_PATHS:
        return
    if _is_number(original) and _is_number(replayed):
        if abs(float(replayed) - float(original)) > numeric_tolerance:
            paths.append(path)
        return
    if isinstance(original, dict) and isinstance(replayed, dict):
        original_keys = set(original)
        replayed_keys = set(replayed)
        for key in sorted(original_keys - replayed_keys):
            paths.append(f"{path}.{key}:missing_replayed")
            if len(paths) >= MAX_DECISION_TREE_DRIFT_PATHS:
                return
        for key in sorted(replayed_keys - original_keys):
            paths.append(f"{path}.{key}:missing_original")
            if len(paths) >= MAX_DECISION_TREE_DRIFT_PATHS:
                return
        for key in sorted(original_keys & replayed_keys):
            _collect_value_drift_paths(
                original[key],
                replayed[key],
                path=f"{path}.{key}",
                numeric_tolerance=numeric_tolerance,
                paths=paths,
            )
            if len(paths) >= MAX_DECISION_TREE_DRIFT_PATHS:
                return
        return
    if isinstance(original, list) and isinstance(replayed, list):
        if len(original) != len(replayed):
            paths.append(f"{path}.length")
            if len(paths) >= MAX_DECISION_TREE_DRIFT_PATHS:
                return
        for index, (original_item, replayed_item) in enumerate(
            zip(original, replayed)
        ):
            _collect_value_drift_paths(
                original_item,
                replayed_item,
                path=f"{path}[{index}]",
                numeric_tolerance=numeric_tolerance,
                paths=paths,
            )
            if len(paths) >= MAX_DECISION_TREE_DRIFT_PATHS:
                return
        return
    if original != replayed:
        paths.append(path)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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
