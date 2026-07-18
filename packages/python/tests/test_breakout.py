from dataclasses import replace
import json
from pathlib import Path
import unittest

from market_cell.cells import BreakoutCell, SupportResistanceCell
from market_cell.engine import AnalysisEngine
from market_cell.graph import default_analysis_graph
from market_cell.models import AnalysisRequest
from market_cell.registry import default_registry
from market_cell.validation import validate_request


ROOT = Path(__file__).resolve().parents[3]
VALIDATION_PATH = ROOT / "validation" / "cells" / "breakout_v0.1.json"


class BreakoutCellTests(unittest.TestCase):
    def test_validation_cases_match_composed_structure_expectations(self):
        validation = json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))
        structure_cell = SupportResistanceCell()
        breakout_cell = BreakoutCell()

        self.assertEqual(
            validation["schema_version"],
            "cell_validation_fixture.v1",
        )
        self.assertEqual(validation["cell_id"], breakout_cell.cell_id)
        self.assertEqual(
            validation["formula_version"],
            breakout_cell.formula_version,
        )
        self.assertEqual(
            validation["dependency_formula_version"],
            SupportResistanceCell.formula_version,
        )
        false_positive_cases = [
            case
            for case in validation["cases"]
            if case["case_type"] == "known_false_positive_guard"
        ]
        self.assertTrue(false_positive_cases)
        self.assertTrue(
            all(case.get("false_positive_note") for case in false_positive_cases)
        )

        for case in validation["cases"]:
            with self.subTest(case_id=case["case_id"]):
                request = AnalysisRequest.from_dict(case["request"])
                validate_request(request)
                structure = structure_cell.analyze(request)
                result = breakout_cell.analyze(request, [structure])
                expected = case["expected"]

                self.assertEqual(
                    structure.metadata["structure_state"],
                    expected["support_state"],
                )
                self.assertEqual(result.direction, expected["direction"])
                self.assertEqual(
                    result.metadata["breakout_state"],
                    expected["breakout_state"],
                )

    def test_confirmed_breakout_preserves_structure_evidence(self):
        validation = json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))
        request = AnalysisRequest.from_dict(validation["cases"][0]["request"])
        structure = SupportResistanceCell().analyze(request)

        result = BreakoutCell().analyze(request, [structure])

        self.assertGreater(result.score, 0)
        self.assertEqual(result.children, [structure])
        self.assertGreaterEqual(len(result.evidence), 2)
        self.assertTrue(result.metadata["fresh_cross"])
        self.assertTrue(result.metadata["candle_confirmed"])
        self.assertTrue(result.metadata["volume_confirmed"])
        self.assertLessEqual(
            result.metadata["volume_baseline_candle_count"],
            20,
        )

    def test_missing_structure_dependency_fails_fast(self):
        validation = json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))
        request = AnalysisRequest.from_dict(validation["cases"][0]["request"])

        with self.assertRaisesRegex(ValueError, "exactly one"):
            BreakoutCell().analyze(request, [])

    def test_mismatched_structure_identity_fails_fast(self):
        validation = json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))
        request = AnalysisRequest.from_dict(validation["cases"][0]["request"])
        structure = SupportResistanceCell().analyze(request)

        with self.assertRaisesRegex(ValueError, "target/horizon"):
            BreakoutCell().analyze(
                request,
                [replace(structure, target="OTHER/USD")],
            )

    def test_structure_formula_drift_fails_fast(self):
        validation = json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))
        request = AnalysisRequest.from_dict(validation["cases"][0]["request"])
        structure = SupportResistanceCell().analyze(request)
        drifted = replace(
            structure,
            metadata={
                **structure.metadata,
                "formula_version": "support_resistance_future_v9",
            },
        )

        with self.assertRaisesRegex(ValueError, "requires support/resistance formula"):
            BreakoutCell().analyze(request, [drifted])

    def test_default_graph_executes_breakout_as_structure_aggregator(self):
        validation = json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))
        request = AnalysisRequest.from_dict(validation["cases"][0]["request"])
        graph = default_analysis_graph()
        breakout_node = next(
            node for node in graph.nodes if node.cell_id == "technical.breakout"
        )
        root = next(
            node for node in graph.nodes if node.node_id == graph.root_node_id
        )

        report = AnalysisEngine().run(request)
        breakout_result = next(
            child
            for child in report.decision.children
            if child.cell_id == "technical.breakout"
        )

        self.assertIsInstance(
            default_registry().resolve("technical.breakout"),
            BreakoutCell,
        )
        self.assertEqual(breakout_node.execution_role, "aggregator")
        self.assertEqual(
            breakout_node.dependencies,
            ["cell:technical.support_resistance"],
        )
        self.assertIn(breakout_node.node_id, root.dependencies)
        self.assertNotIn("cell:technical.support_resistance", root.dependencies)
        self.assertEqual(graph.graph_version, "0.4.0")
        self.assertEqual(breakout_result.direction, "bullish")
        self.assertEqual(
            breakout_result.children[0].cell_id,
            "technical.support_resistance",
        )


if __name__ == "__main__":
    unittest.main()
