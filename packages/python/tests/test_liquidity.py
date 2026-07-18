import json
from pathlib import Path
import tempfile
import unittest

from market_cell.cells import LiquidityCell
from market_cell.data import OrderBookSnapshot
from market_cell.engine import AnalysisEngine
from market_cell.execution import build_local_execution_plan
from market_cell.graph import (
    default_analysis_graph,
    liquidity_analysis_graph,
    validate_cell_graph_definition,
)
from market_cell.inputs import (
    CellInputBundle,
    InputCompositionError,
    InputSnapshot,
    ResolvedCellInput,
)
from market_cell.models import AnalysisRequest
from market_cell.registry import default_registry
from market_cell.replay import ReplayRunner
from market_cell.reports import FileSystemReportStore
from market_cell.validation import validate_request


ROOT = Path(__file__).resolve().parents[3]
VALIDATION_PATH = ROOT / "validation" / "cells" / "liquidity_v0.1.json"


class LiquidityCellTests(unittest.TestCase):
    def test_validation_cases_cover_direction_boundaries_and_false_positives(self):
        validation = _validation()
        cell = LiquidityCell()

        self.assertEqual(validation["schema_version"], "cell_validation_fixture.v1")
        self.assertEqual(validation["cell_id"], cell.cell_id)
        self.assertEqual(validation["formula_version"], cell.formula_version)
        false_positive_cases = [
            case
            for case in validation["cases"]
            if case["case_type"] == "known_false_positive_guard"
        ]
        self.assertGreaterEqual(len(false_positive_cases), 3)
        self.assertTrue(
            all(case.get("false_positive_note") for case in false_positive_cases)
        )

        for case in validation["cases"]:
            with self.subTest(case_id=case["case_id"]):
                request = AnalysisRequest.from_dict(case["request"])
                validate_request(request)
                order_book = OrderBookSnapshot.from_dict(case["order_book"])

                result = cell.analyze_inputs(_bundle(request, order_book))
                expected = case["expected"]

                self.assertEqual(result.direction, expected["direction"])
                self.assertEqual(
                    result.metadata["liquidity_state"],
                    expected["liquidity_state"],
                )
                if expected.get("active_guard"):
                    self.assertIn(
                        expected["active_guard"],
                        result.metadata["active_guards"],
                    )
                for count_field in ("bid_level_count", "ask_level_count"):
                    if count_field in expected:
                        self.assertEqual(
                            result.metadata[count_field],
                            expected[count_field],
                        )
                self.assertEqual(result.manipulation_risk, 0)
                self.assertLessEqual(result.confidence, 88)
                self.assertEqual(
                    result.metadata["manipulation_inference"],
                    "not_supported_by_single_snapshot",
                )

    def test_cell_consumes_typed_order_book_and_preserves_provenance(self):
        case = _case("distributed_bid_depth_is_bullish")
        request = AnalysisRequest.from_dict(case["request"])
        order_book = OrderBookSnapshot.from_dict(case["order_book"])

        result = LiquidityCell().analyze_inputs(_bundle(request, order_book))

        self.assertEqual(result.direction, "bullish")
        self.assertGreater(
            result.metadata["bid_depth_notional"],
            result.metadata["ask_depth_notional"],
        )
        self.assertEqual(result.metadata["depth_window_bps"], 100)
        self.assertEqual(result.metadata["depth_unit"], "quote_notional")
        self.assertEqual(result.metadata["provenance_sequence"], 101)
        self.assertEqual(result.metadata["fetch_latency_ms"], 25)
        self.assertEqual(result.metadata["quality_flags"], [])
        self.assertEqual(len(result.evidence), 3)
        provenance = next(
            evidence
            for evidence in result.evidence
            if evidence.source == "order_book.provenance"
        )
        self.assertEqual(provenance.freshness, 98.75)

    def test_request_only_entrypoint_fails_explicitly(self):
        request = AnalysisRequest.from_dict(_validation()["cases"][0]["request"])

        with self.assertRaisesRegex(
            InputCompositionError,
            "typed order_book_snapshot",
        ):
            LiquidityCell().analyze(request)

    def test_registry_is_a_capability_superset_of_the_default_graph(self):
        registry = default_registry()
        default_graph = default_analysis_graph()
        liquidity_graph = liquidity_analysis_graph()

        validated = validate_cell_graph_definition(
            liquidity_graph,
            registry.manifests(),
        )
        default_cell_ids = {node.cell_id for node in default_graph.nodes}
        liquidity_node = next(
            node
            for node in liquidity_graph.nodes
            if node.cell_id == "microstructure.liquidity"
        )
        root = next(
            node
            for node in liquidity_graph.nodes
            if node.node_id == liquidity_graph.root_node_id
        )
        microstructure_organ = next(
            organ
            for organ in liquidity_graph.organs
            if organ.organ_id == "organ.market_microstructure"
        )

        self.assertIsInstance(
            registry.resolve("microstructure.liquidity"),
            LiquidityCell,
        )
        self.assertNotIn("microstructure.liquidity", default_cell_ids)
        self.assertGreater(len(registry.all_cells()), len(default_graph.nodes))
        self.assertEqual(liquidity_graph.graph_id, "market.liquidity_analysis")
        self.assertEqual(liquidity_graph.graph_version, "0.2.0")
        self.assertIn(liquidity_node.node_id, root.dependencies)
        self.assertEqual(microstructure_organ.node_ids, [liquidity_node.node_id])
        self.assertEqual(validated.topological_levels[-1], [root.node_id])

    def test_planner_binds_order_book_only_to_liquidity_cell(self):
        request, order_book = _inputs("distributed_bid_depth_is_bullish")
        request_snapshot = InputSnapshot.from_analysis_request(request)
        order_book_snapshot = order_book.to_input_snapshot(horizon=request.horizon)

        plan = build_local_execution_plan(
            default_registry(),
            request,
            graph_definition=liquidity_analysis_graph(),
            input_references=[
                request_snapshot.to_reference(),
                order_book_snapshot.to_reference(),
            ],
        )
        references = {
            reference.reference_id: reference for reference in plan.input_references
        }

        for node in plan.nodes:
            kinds = [
                references[reference_id].input_kind
                for reference_id in node.input_reference_ids
            ]
            if node.cell_id == "microstructure.liquidity":
                self.assertEqual(
                    kinds,
                    ["analysis_request", "order_book_snapshot"],
                )
            else:
                self.assertEqual(kinds, ["analysis_request"])

    def test_missing_order_book_fails_during_liquidity_graph_planning(self):
        request = AnalysisRequest.from_dict(_validation()["cases"][0]["request"])

        with self.assertRaisesRegex(
            InputCompositionError,
            "missing required input kinds: order_book_snapshot",
        ):
            build_local_execution_plan(
                default_registry(),
                request,
                graph_definition=liquidity_analysis_graph(),
            )

    def test_default_engine_remains_order_book_optional(self):
        request = AnalysisRequest.from_dict(_validation()["cases"][0]["request"])

        report = AnalysisEngine().run(request)

        self.assertNotIn(
            "microstructure.liquidity",
            {child.cell_id for child in report.decision.children},
        )
        self.assertNotIn("microstructure.liquidity", report.formula_versions)

    def test_liquidity_graph_persists_and_replays_all_inputs_stably(self):
        request, order_book = _inputs("distributed_bid_depth_is_bullish")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(
                graph_definition=liquidity_analysis_graph(),
                report_store=store,
            ).run(
                request,
                input_snapshots=[
                    order_book.to_input_snapshot(horizon=request.horizon)
                ],
            )
            run = store.load_run(report.run_id or "")
            comparison = ReplayRunner(
                store,
                engine_factory=lambda: AnalysisEngine(
                    graph_definition=liquidity_analysis_graph()
                ),
            ).replay(report.report_id or "")

        self.assertEqual(
            [item["input_kind"] for item in run["input_snapshots"]],
            ["analysis_request", "order_book_snapshot"],
        )
        self.assertEqual(
            run["metadata"]["cell_graph_definition"]["graph_id"],
            "market.liquidity_analysis",
        )
        self.assertIn("microstructure.liquidity", run["formula_versions"])
        self.assertTrue(comparison.input_hash_matches)
        self.assertTrue(comparison.result_stable)
        self.assertEqual(comparison.formula_version_changes, {})
        self.assertEqual(comparison.graph_definition_changes, {})

    def test_liquidity_fragility_changes_root_risk_posture(self):
        request, order_book = _inputs("wide_spread_blocks_bid_imbalance")

        report = AnalysisEngine(
            graph_definition=liquidity_analysis_graph(),
        ).run(
            request,
            input_snapshots=[
                order_book.to_input_snapshot(horizon=request.horizon)
            ],
        )
        liquidity = next(
            child
            for child in report.decision.children
            if child.cell_id == "microstructure.liquidity"
        )

        self.assertEqual(liquidity.direction, "conflict")
        self.assertGreaterEqual(liquidity.volatility_risk, 55)
        self.assertEqual(report.decision.risk_level, "extreme")
        self.assertEqual(report.decision.action_posture, "avoid_chasing")
        self.assertEqual(liquidity.manipulation_risk, 0)


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
        OrderBookSnapshot.from_dict(case["order_book"]),
    )


def _bundle(
    request: AnalysisRequest,
    order_book: OrderBookSnapshot,
) -> CellInputBundle:
    request_snapshot = InputSnapshot.from_analysis_request(request)
    order_book_snapshot = order_book.to_input_snapshot(horizon=request.horizon)
    return CellInputBundle(
        node_id="cell:microstructure.liquidity",
        analysis_request=request,
        resolved_inputs=(
            ResolvedCellInput(
                reference=request_snapshot.to_reference(),
                snapshot=request_snapshot,
            ),
            ResolvedCellInput(
                reference=order_book_snapshot.to_reference(),
                snapshot=order_book_snapshot,
            ),
        ),
        required_input_kinds=(
            "analysis_request",
            "order_book_snapshot",
        ),
    )


if __name__ == "__main__":
    unittest.main()
