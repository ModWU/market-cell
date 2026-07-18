import json
from pathlib import Path
import unittest

from market_cell.cells import SupportResistanceCell
from market_cell.graph import default_analysis_graph
from market_cell.models import AnalysisRequest
from market_cell.registry import default_registry
from market_cell.validation import validate_request


ROOT = Path(__file__).resolve().parents[3]
VALIDATION_PATH = (
    ROOT / "validation" / "cells" / "support_resistance_v0.1.json"
)


class SupportResistanceCellTests(unittest.TestCase):
    def test_validation_cases_match_versioned_expectations(self):
        validation = json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))
        cell = SupportResistanceCell()

        self.assertEqual(
            validation["schema_version"],
            "cell_validation_fixture.v1",
        )
        self.assertEqual(validation["cell_id"], cell.cell_id)
        self.assertEqual(validation["formula_version"], cell.formula_version)
        self.assertTrue(validation["known_limitations"])
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
                result = cell.analyze(request)
                expected = case["expected"]

                self.assertEqual(result.direction, expected["direction"])
                self.assertEqual(
                    result.metadata["structure_state"],
                    expected["structure_state"],
                )
                if "minimum_support_touches" in expected:
                    self.assertGreaterEqual(
                        result.metadata["support_touch_count"],
                        expected["minimum_support_touches"],
                    )
                if "minimum_resistance_touches" in expected:
                    self.assertGreaterEqual(
                        result.metadata["resistance_touch_count"],
                        expected["minimum_resistance_touches"],
                    )

    def test_directional_signal_has_manifest_and_evidence(self):
        validation = json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))
        case = validation["cases"][0]
        cell = SupportResistanceCell()

        result = cell.analyze(AnalysisRequest.from_dict(case["request"]))
        manifest = cell.manifest()

        self.assertEqual(manifest.status, "experimental")
        self.assertEqual(
            manifest.formula_version,
            "support_resistance_cluster_rejection_v0.1",
        )
        self.assertGreaterEqual(len(result.evidence), 2)
        self.assertGreater(result.confidence, 0)
        self.assertGreater(result.score, 0)

    def test_cell_is_registered_and_part_of_default_technical_organ(self):
        registry = default_registry()
        graph = default_analysis_graph()
        technical_organ = next(
            organ
            for organ in graph.organs
            if organ.organ_id == "organ.technical_structure"
        )
        root = next(
            node for node in graph.nodes if node.node_id == graph.root_node_id
        )
        breakout = next(
            node for node in graph.nodes if node.cell_id == "technical.breakout"
        )

        self.assertIsInstance(
            registry.resolve("technical.support_resistance"),
            SupportResistanceCell,
        )
        self.assertIn(
            "cell:technical.support_resistance",
            technical_organ.node_ids,
        )
        self.assertNotIn(
            "cell:technical.support_resistance",
            root.dependencies,
        )
        self.assertEqual(
            breakout.dependencies,
            ["cell:technical.support_resistance"],
        )
        self.assertEqual(graph.graph_version, "0.4.0")

    def test_stale_levels_outside_bounded_history_are_ignored(self):
        stale = [
            {
                "timestamp": f"stale-{index}",
                "open": 92,
                "high": 95,
                "low": 90,
                "close": 93,
                "volume": 1000,
            }
            for index in range(50)
        ]
        recent = [
            {
                "timestamp": f"recent-{index}",
                "open": 102,
                "high": 105,
                "low": 100 + (index % 3) * 0.1,
                "close": 103,
                "volume": 1000,
            }
            for index in range(48)
        ]
        latest = {
            "timestamp": "latest",
            "open": 101.5,
            "high": 104,
            "low": 99.8,
            "close": 103.2,
            "volume": 1100,
        }
        request = AnalysisRequest.from_dict(
            {
                "target": "TEST/USD",
                "horizon": "1h",
                "candles": [*stale, *recent, latest],
            }
        )

        result = SupportResistanceCell().analyze(request)

        self.assertEqual(result.metadata["history_candle_count"], 48)
        self.assertAlmostEqual(result.metadata["support_level"], 100.1, places=1)
        self.assertNotAlmostEqual(result.metadata["support_level"], 90, places=1)


if __name__ == "__main__":
    unittest.main()
