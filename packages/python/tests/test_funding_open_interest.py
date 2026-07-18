from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from market_cell.cells import FundingOpenInterestCell
from market_cell.cells.funding_open_interest import KNOWN_POSITIONING_STATES
from market_cell.data import (
    DataProvenance,
    FundingOpenInterestPoint,
    FundingOpenInterestSnapshot,
)
from market_cell.engine import AnalysisEngine
from market_cell.execution import build_local_execution_plan
from market_cell.graph import (
    default_analysis_graph,
    derivatives_analysis_graph,
    validate_cell_graph_definition,
)
from market_cell.inputs import (
    CellInputBundle,
    InputCompositionError,
    InputIntegrityError,
    InputSnapshot,
    LocalInputResolver,
    ResolvedCellInput,
)
from market_cell.models import AnalysisRequest
from market_cell.registry import default_registry
from market_cell.replay import ReplayRunner
from market_cell.reports import FileSystemReportStore
from market_cell.validation import validate_request


ROOT = Path(__file__).resolve().parents[3]
VALIDATION_PATH = (
    ROOT / "validation" / "cells" / "funding_open_interest_v0.1.json"
)


class FundingOpenInterestCellTests(unittest.TestCase):
    def test_validation_cases_cover_direction_boundaries_and_false_positives(self):
        validation = _validation()
        cell = FundingOpenInterestCell()

        self.assertEqual(validation["schema_version"], "cell_validation_fixture.v1")
        self.assertEqual(validation["cell_id"], cell.cell_id)
        self.assertEqual(validation["formula_version"], cell.formula_version)
        self.assertTrue(
            {
                case["expected"]["positioning_state"]
                for case in validation["cases"]
            }.issubset(KNOWN_POSITIONING_STATES)
        )
        false_positive_cases = [
            case
            for case in validation["cases"]
            if case["case_type"] == "known_false_positive_guard"
        ]
        self.assertGreaterEqual(len(false_positive_cases), 5)
        self.assertTrue(
            all(case.get("false_positive_note") for case in false_positive_cases)
        )

        for case in validation["cases"]:
            with self.subTest(case_id=case["case_id"]):
                request = AnalysisRequest.from_dict(case["request"])
                validate_request(request)
                derivatives = FundingOpenInterestSnapshot.from_dict(
                    case["snapshot"]
                )

                result = cell.analyze_inputs(_bundle(request, derivatives))
                expected = case["expected"]

                self.assertEqual(result.direction, expected["direction"])
                self.assertEqual(
                    result.metadata["positioning_state"],
                    expected["positioning_state"],
                )
                for flag in (
                    "funding_crowded",
                    "funding_anomalous",
                    "open_interest_anomalous",
                ):
                    if flag in expected:
                        self.assertEqual(result.metadata[flag], expected[flag])
                if expected.get("active_guard"):
                    self.assertIn(
                        expected["active_guard"],
                        result.metadata["active_guards"],
                    )
                if "minimum_volatility_risk" in expected:
                    self.assertGreaterEqual(
                        result.volatility_risk,
                        expected["minimum_volatility_risk"],
                    )
                if "maximum_confidence" in expected:
                    self.assertLessEqual(
                        result.confidence,
                        expected["maximum_confidence"],
                    )
                self.assertLessEqual(result.confidence, 88)
                self.assertEqual(result.manipulation_risk, 0)
                expected_assessment_status = (
                    "unavailable"
                    if expected["positioning_state"]
                    in {"insufficient_history", "degraded_input"}
                    else "available"
                )
                self.assertEqual(
                    result.metadata["risk_assessment_status"],
                    expected_assessment_status,
                )
                self.assertEqual(
                    result.metadata["manipulation_inference"],
                    "not_supported_by_positioning_alone",
                )

    def test_manifest_and_evidence_expose_normalization_and_provenance(self):
        request, derivatives = _inputs("leveraged_long_buildup_is_bullish")
        cell = FundingOpenInterestCell()

        result = cell.analyze_inputs(_bundle(request, derivatives))
        manifest = cell.manifest()

        self.assertEqual(manifest.status, "experimental")
        self.assertEqual(
            manifest.required_input_kinds,
            ["analysis_request", "funding_open_interest_snapshot"],
        )
        self.assertEqual(manifest.risk_dimensions, ["volatility_risk"])
        self.assertEqual(result.metadata["funding_normalization_hours"], 8)
        self.assertEqual(result.metadata["notional_currency"], "USD")
        self.assertEqual(result.metadata["market_type"], "perpetual_future")
        self.assertEqual(result.metadata["fetch_latency_ms"], 100)
        self.assertEqual(len(result.evidence), 4)
        self.assertIn("不单独证明操纵", result.explanation)

    def test_request_only_entrypoint_fails_explicitly(self):
        request = AnalysisRequest.from_dict(_validation()["cases"][0]["request"])

        with self.assertRaisesRegex(
            InputCompositionError,
            "typed funding_open_interest_snapshot",
        ):
            FundingOpenInterestCell().analyze(request)

    def test_domain_contract_rejects_ambiguous_or_misaligned_data(self):
        _, derivatives = _inputs("stable_positioning_is_normal")

        with self.assertRaisesRegex(ValueError, "perpetual_future"):
            replace(
                derivatives,
                provenance=replace(
                    derivatives.provenance,
                    market_type="futures",
                ),
            )
        with self.assertRaisesRegex(ValueError, "linear contracts"):
            replace(derivatives, contract_type="inverse")
        with self.assertRaisesRegex(ValueError, "funding rate type"):
            replace(derivatives, funding_rate_type="annualized")
        with self.assertRaisesRegex(ValueError, "uppercase asset code"):
            replace(derivatives, notional_currency="usd")
        with self.assertRaisesRegex(ValueError, "sorted ascending"):
            replace(
                derivatives,
                points=[derivatives.points[1], derivatives.points[0]],
            )
        with self.assertRaisesRegex(ValueError, "provenance event time"):
            replace(
                derivatives,
                provenance=replace(
                    derivatives.provenance,
                    event_time_ms=derivatives.provenance.event_time_ms + 1,
                ),
            )
        with self.assertRaisesRegex(ValueError, "decimal-rate boundary"):
            FundingOpenInterestPoint(
                timestamp_ms=0,
                funding_rate=5.0,
                open_interest_notional=1,
                mark_price=1,
            )

    def test_price_adjustment_prevents_quote_notional_false_surge(self):
        request, derivatives = _inputs(
            "price_only_notional_growth_is_not_position_growth"
        )

        result = FundingOpenInterestCell().analyze_inputs(
            _bundle(request, derivatives)
        )

        self.assertGreater(
            result.metadata["latest_open_interest_notional_change_pct"],
            2.5,
        )
        self.assertLess(
            abs(
                result.metadata[
                    "latest_open_interest_exposure_change_pct"
                ]
            ),
            0.1,
        )
        self.assertFalse(result.metadata["open_interest_anomalous"])
        self.assertEqual(result.metadata["positioning_state"], "normal")

    def test_predicted_funding_semantics_reduce_confidence(self):
        request, predicted = _inputs("stable_positioning_is_normal")
        settled = replace(predicted, funding_rate_type="settled")

        predicted_result = FundingOpenInterestCell().analyze_inputs(
            _bundle(request, predicted)
        )
        settled_result = FundingOpenInterestCell().analyze_inputs(
            _bundle(request, settled)
        )

        self.assertEqual(predicted_result.metadata["funding_rate_type"], "predicted")
        self.assertEqual(settled_result.metadata["funding_rate_type"], "settled")
        self.assertEqual(
            settled_result.confidence - predicted_result.confidence,
            5,
        )

    def test_snapshot_envelope_and_content_tampering_are_rejected(self):
        request, derivatives = _inputs("stable_positioning_is_normal")
        snapshot = derivatives.to_input_snapshot(horizon=request.horizon)

        with self.assertRaisesRegex(ValueError, "envelope mismatch: target"):
            FundingOpenInterestSnapshot.from_input_snapshot(
                replace(snapshot, target="OTHER/USD")
            )

        tampered_payload = {
            **snapshot.payload,
            "points": [
                *snapshot.payload["points"][:-1],
                {
                    **snapshot.payload["points"][-1],
                    "open_interest_notional": 999999,
                },
            ],
        }
        with self.assertRaisesRegex(InputIntegrityError, "content_hash"):
            LocalInputResolver().register(
                replace(snapshot, payload=tampered_payload)
            )

    def test_bounded_history_ignores_stale_positioning_regime(self):
        request, derivatives = _inputs("leveraged_long_buildup_is_bullish")
        interval = derivatives.sample_interval_ms
        recent_start = 100 * interval
        recent = [
            replace(
                point,
                timestamp_ms=recent_start + index * interval,
            )
            for index, point in enumerate(derivatives.points)
        ]
        stale = [
            FundingOpenInterestPoint(
                timestamp_ms=index * interval,
                funding_rate=0.001,
                open_interest_notional=10_000 + index * 100,
                mark_price=200 + index,
            )
            for index in range(100)
        ]
        bounded = replace(
            derivatives,
            points=[*stale, *recent],
            provenance=replace(
                derivatives.provenance,
                event_time_ms=recent[-1].timestamp_ms,
                fetched_at_ms=recent[-1].timestamp_ms + 100,
            ),
        )

        result = FundingOpenInterestCell().analyze_inputs(
            _bundle(request, bounded)
        )

        self.assertEqual(result.metadata["history_point_count"], 48)
        self.assertEqual(
            result.metadata["positioning_state"],
            "leveraged_long_buildup",
        )

    def test_registry_graph_and_planner_keep_derivatives_input_explicit(self):
        registry = default_registry()
        default_graph = default_analysis_graph()
        graph = derivatives_analysis_graph()
        validated = validate_cell_graph_definition(graph, registry.manifests())
        request, derivatives = _inputs("leveraged_long_buildup_is_bullish")
        request_snapshot = InputSnapshot.from_analysis_request(request)
        derivatives_snapshot = derivatives.to_input_snapshot(
            horizon=request.horizon
        )

        plan = build_local_execution_plan(
            registry,
            request,
            graph_definition=graph,
            input_references=[
                request_snapshot.to_reference(),
                derivatives_snapshot.to_reference(),
            ],
        )
        references = {
            reference.reference_id: reference
            for reference in plan.input_references
        }
        positioning_node = next(
            node
            for node in graph.nodes
            if node.cell_id == "crypto.funding_open_interest"
        )
        root = next(
            node for node in graph.nodes if node.node_id == graph.root_node_id
        )
        organ = next(
            organ
            for organ in graph.organs
            if organ.organ_id == "organ.derivatives_positioning"
        )

        self.assertIsInstance(
            registry.resolve("crypto.funding_open_interest"),
            FundingOpenInterestCell,
        )
        self.assertNotIn(
            "crypto.funding_open_interest",
            {node.cell_id for node in default_graph.nodes},
        )
        self.assertEqual(graph.graph_id, "market.derivatives_analysis")
        self.assertEqual(graph.graph_version, "0.1.0")
        self.assertIn(positioning_node.node_id, root.dependencies)
        self.assertEqual(organ.node_ids, [positioning_node.node_id])
        self.assertEqual(validated.topological_levels[-1], [root.node_id])

        for node in plan.nodes:
            kinds = [
                references[reference_id].input_kind
                for reference_id in node.input_reference_ids
            ]
            if node.cell_id == "crypto.funding_open_interest":
                self.assertEqual(
                    kinds,
                    [
                        "analysis_request",
                        "funding_open_interest_snapshot",
                    ],
                )
            else:
                self.assertEqual(kinds, ["analysis_request"])

    def test_missing_derivatives_input_fails_during_planning(self):
        request = AnalysisRequest.from_dict(_validation()["cases"][0]["request"])

        with self.assertRaisesRegex(
            InputCompositionError,
            "missing required input kinds: funding_open_interest_snapshot",
        ):
            build_local_execution_plan(
                default_registry(),
                request,
                graph_definition=derivatives_analysis_graph(),
            )

    def test_default_engine_remains_derivatives_optional(self):
        request = AnalysisRequest.from_dict(_validation()["cases"][0]["request"])

        report = AnalysisEngine().run(request)

        self.assertNotIn(
            "crypto.funding_open_interest",
            {child.cell_id for child in report.decision.children},
        )
        self.assertNotIn(
            "crypto.funding_open_interest",
            report.formula_versions,
        )

    def test_derivatives_graph_persists_and_replays_all_inputs_stably(self):
        request, derivatives = _inputs("crowded_long_buildup_blocks_direction")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(
                graph_definition=derivatives_analysis_graph(),
                report_store=store,
            ).run(
                request,
                input_snapshots=[
                    derivatives.to_input_snapshot(horizon=request.horizon)
                ],
            )
            run = store.load_run(report.run_id or "")
            comparison = ReplayRunner(
                store,
                engine_factory=lambda: AnalysisEngine(
                    graph_definition=derivatives_analysis_graph()
                ),
            ).replay(report.report_id or "")

        self.assertEqual(
            [item["input_kind"] for item in run["input_snapshots"]],
            ["analysis_request", "funding_open_interest_snapshot"],
        )
        self.assertEqual(
            run["metadata"]["cell_graph_definition"]["graph_id"],
            "market.derivatives_analysis",
        )
        self.assertIn("crypto.funding_open_interest", run["formula_versions"])
        self.assertTrue(comparison.input_hash_matches)
        self.assertTrue(comparison.result_stable)
        self.assertEqual(comparison.formula_version_changes, {})
        self.assertEqual(comparison.graph_definition_changes, {})

    def test_leverage_crowding_changes_root_risk_posture(self):
        request, derivatives = _inputs("crowded_long_buildup_blocks_direction")

        report = AnalysisEngine(
            graph_definition=derivatives_analysis_graph(),
        ).run(
            request,
            input_snapshots=[
                derivatives.to_input_snapshot(horizon=request.horizon)
            ],
        )
        positioning = next(
            child
            for child in report.decision.children
            if child.cell_id == "crypto.funding_open_interest"
        )

        self.assertEqual(positioning.direction, "conflict")
        self.assertGreaterEqual(positioning.volatility_risk, 80)
        self.assertEqual(report.decision.risk_level, "extreme")
        self.assertEqual(report.decision.action_posture, "avoid_chasing")
        self.assertEqual(positioning.manipulation_risk, 0)
        self.assertEqual(
            report.decision.metadata["weights"][
                "crypto.funding_open_interest"
            ],
            0.9,
        )
        positioning_evidence = next(
            evidence
            for evidence in report.decision.evidence
            if evidence.source == "crypto.funding_open_interest"
        )
        self.assertEqual(positioning_evidence.weight, 0.9)


def _validation():
    return json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))


def _case(case_id: str):
    return next(
        case for case in _validation()["cases"] if case["case_id"] == case_id
    )


def _inputs(case_id: str):
    case = _case(case_id)
    return (
        AnalysisRequest.from_dict(case["request"]),
        FundingOpenInterestSnapshot.from_dict(case["snapshot"]),
    )


def _bundle(
    request: AnalysisRequest,
    derivatives: FundingOpenInterestSnapshot,
) -> CellInputBundle:
    request_snapshot = InputSnapshot.from_analysis_request(request)
    derivatives_snapshot = derivatives.to_input_snapshot(horizon=request.horizon)
    return CellInputBundle(
        node_id="cell:crypto.funding_open_interest",
        analysis_request=request,
        resolved_inputs=(
            ResolvedCellInput(
                reference=request_snapshot.to_reference(),
                snapshot=request_snapshot,
            ),
            ResolvedCellInput(
                reference=derivatives_snapshot.to_reference(),
                snapshot=derivatives_snapshot,
            ),
        ),
        required_input_kinds=(
            "analysis_request",
            "funding_open_interest_snapshot",
        ),
    )


if __name__ == "__main__":
    unittest.main()
