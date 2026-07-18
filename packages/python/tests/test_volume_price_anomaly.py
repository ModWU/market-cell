from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from market_cell.cells import (
    ManipulationRiskCell,
    VolumeCell,
    VolumePriceAnomalyCell,
)
from market_cell.engine import AnalysisEngine
from market_cell.graph import default_analysis_graph
from market_cell.models import AnalysisRequest
from market_cell.registry import default_registry
from market_cell.replay import ReplayRunner
from market_cell.reports import FileSystemReportStore
from market_cell.validation import validate_request


ROOT = Path(__file__).resolve().parents[3]
VALIDATION_PATH = (
    ROOT / "validation" / "cells" / "volume_price_anomaly_v0.2.json"
)


class VolumePriceAnomalyCellTests(unittest.TestCase):
    def test_validation_cases_match_robust_anomaly_expectations(self):
        validation = _validation()
        cell = VolumePriceAnomalyCell()

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

                result = cell.analyze(request)
                expected = case["expected"]

                self.assertEqual(result.direction, expected["direction"])
                self.assertEqual(
                    result.metadata["anomaly_state"],
                    expected["anomaly_state"],
                )
                for flag in ("volume_anomalous", "price_anomalous"):
                    if flag in expected:
                        self.assertEqual(result.metadata[flag], expected[flag])
                if "minimum_manipulation_risk" in expected:
                    self.assertGreaterEqual(
                        result.manipulation_risk,
                        expected["minimum_manipulation_risk"],
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
                self.assertEqual(
                    result.metadata["manipulation_inference"],
                    "risk_pattern_not_proof",
                )

    def test_manifest_and_evidence_expose_formula_boundaries(self):
        request = _request("volume_absorption_after_spike")
        cell = VolumePriceAnomalyCell()

        result = cell.analyze(request)
        manifest = cell.manifest()

        self.assertEqual(manifest.status, "experimental")
        self.assertEqual(
            manifest.formula_version,
            "robust_volume_price_anomaly_v0.2",
        )
        self.assertEqual(
            manifest.risk_dimensions,
            ["volatility_risk", "manipulation_risk"],
        )
        self.assertEqual(len(result.evidence), 3)
        self.assertGreater(result.metadata["volume_robust_z"], 3.5)
        self.assertEqual(result.score, 0)
        self.assertIn("不能证明", result.explanation)

    def test_bounded_history_ignores_stale_volume_regime(self):
        example = _request("volume_absorption_after_spike")
        history_template = example.candles[:-1]
        recent_history = [
            replace(
                history_template[index % len(history_template)],
                timestamp=f"recent-{index}",
            )
            for index in range(48)
        ]
        stale = [
            replace(
                history_template[0],
                timestamp=f"stale-{index}",
                volume=20_000,
            )
            for index in range(50)
        ]
        request = replace(
            example,
            candles=[*stale, *recent_history, example.candles[-1]],
        )

        result = VolumePriceAnomalyCell().analyze(request)

        self.assertEqual(result.metadata["history_candle_count"], 48)
        self.assertEqual(result.metadata["anomaly_state"], "volume_absorption")
        self.assertLess(result.metadata["historical_volume_median"], 2_000)

    def test_volume_cell_delegates_anomaly_risk(self):
        result = VolumeCell().analyze(_request("volume_absorption_after_spike"))

        self.assertEqual(VolumeCell.formula_version, "volume_direction_confirmation_v0.2")
        self.assertEqual(result.manipulation_risk, 0)
        self.assertEqual(
            result.metadata["anomaly_risk_delegated_to"],
            "risk.volume_price_anomaly",
        )

    def test_manipulation_aggregator_validates_anomaly_dependency(self):
        request = _request("volume_absorption_after_spike")
        anomaly = VolumePriceAnomalyCell().analyze(request)
        cell = ManipulationRiskCell()

        result = cell.analyze(request, [anomaly])

        self.assertEqual(result.children, [anomaly])
        self.assertEqual(result.metadata["anomaly_state"], "volume_absorption")
        self.assertGreater(result.manipulation_risk, 35)
        self.assertEqual(result.direction, "conflict")

        with self.assertRaisesRegex(ValueError, "exactly one"):
            cell.analyze(request, [])
        with self.assertRaisesRegex(ValueError, "target/horizon"):
            cell.analyze(request, [replace(anomaly, target="OTHER/USD")])
        drifted = replace(
            anomaly,
            metadata={
                **anomaly.metadata,
                "formula_version": "future_anomaly_formula_v9",
            },
        )
        with self.assertRaisesRegex(ValueError, "requires volume/price anomaly"):
            cell.analyze(request, [drifted])
        unknown_state = replace(
            anomaly,
            metadata={
                **anomaly.metadata,
                "anomaly_state": "unknown_future_state",
            },
        )
        with self.assertRaisesRegex(ValueError, "unknown anomaly state"):
            cell.analyze(request, [unknown_state])

    def test_manipulation_aggregator_dampens_duplicate_price_range(self):
        request = _request("synchronized_expansion_up")
        anomaly = VolumePriceAnomalyCell().analyze(request)

        result = ManipulationRiskCell().analyze(request, [anomaly])

        self.assertTrue(anomaly.metadata["price_anomalous"])
        self.assertGreater(result.metadata["range_component"], 0)
        self.assertEqual(result.metadata["range_component_weight"], 0.5)
        self.assertAlmostEqual(
            result.manipulation_risk,
            anomaly.manipulation_risk
            + result.metadata["range_component"] * 0.5
            + result.metadata["wick_component"],
            places=3,
        )

    def test_default_graph_composes_anomaly_before_manipulation(self):
        graph = default_analysis_graph()
        registry = default_registry()
        anomaly_node = next(
            node
            for node in graph.nodes
            if node.cell_id == "risk.volume_price_anomaly"
        )
        manipulation_node = next(
            node for node in graph.nodes if node.cell_id == "risk.manipulation"
        )
        root = next(
            node for node in graph.nodes if node.node_id == graph.root_node_id
        )
        risk_organ = next(
            organ for organ in graph.organs if organ.organ_id == "organ.market_risk"
        )

        report = AnalysisEngine().run(_request("volume_absorption_after_spike"))
        manipulation = next(
            child
            for child in report.decision.children
            if child.cell_id == "risk.manipulation"
        )

        self.assertIsInstance(
            registry.resolve("risk.volume_price_anomaly"),
            VolumePriceAnomalyCell,
        )
        self.assertEqual(graph.graph_version, "0.4.0")
        self.assertEqual(anomaly_node.execution_role, "leaf")
        self.assertEqual(manipulation_node.execution_role, "aggregator")
        self.assertEqual(manipulation_node.dependencies, [anomaly_node.node_id])
        self.assertIn(manipulation_node.node_id, root.dependencies)
        self.assertNotIn(anomaly_node.node_id, root.dependencies)
        self.assertIn(anomaly_node.node_id, risk_organ.node_ids)
        self.assertEqual(
            manipulation.children[0].cell_id,
            "risk.volume_price_anomaly",
        )

    def test_anomaly_risk_changes_root_posture_without_claiming_manipulation(self):
        report = AnalysisEngine().run(_request("volume_absorption_after_spike"))
        manipulation = next(
            child
            for child in report.decision.children
            if child.cell_id == "risk.manipulation"
        )

        self.assertGreaterEqual(manipulation.manipulation_risk, 35)
        self.assertEqual(report.decision.risk_level, "high")
        self.assertEqual(report.decision.action_posture, "reduce_exposure")
        self.assertIn("不证明", manipulation.explanation)

    def test_default_graph_replays_new_nested_risk_result_stably(self):
        request = _request("synchronized_expansion_up")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(report_store=store).run(request)
            comparison = ReplayRunner(store).replay(report.report_id or "")

        self.assertTrue(comparison.input_hash_matches)
        self.assertTrue(comparison.result_stable)
        self.assertEqual(comparison.formula_version_changes, {})
        self.assertEqual(comparison.graph_definition_changes, {})


def _validation():
    return json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))


def _request(case_id: str) -> AnalysisRequest:
    case = next(
        case for case in _validation()["cases"] if case["case_id"] == case_id
    )
    return AnalysisRequest.from_dict(case["request"])


if __name__ == "__main__":
    unittest.main()
