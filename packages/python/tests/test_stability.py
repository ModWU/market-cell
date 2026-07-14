import unittest

from market_cell.engine import AnalysisEngine
from market_cell.graph import default_analysis_graph
from market_cell.models import AnalysisRequest, Candle, CellResult, MarketEvent
from market_cell.registry import default_registry


def sample_request() -> AnalysisRequest:
    return AnalysisRequest(
        target="BTC/USD",
        horizon="1h",
        candles=[
            Candle("t1", 100, 102, 99, 101, 1000),
            Candle("t2", 101, 104, 100, 103, 1200),
            Candle("t3", 103, 106, 102, 105, 1400),
            Candle("t4", 105, 108, 104, 107, 2200),
        ],
        events=[
            MarketEvent("positive flow", "institution", 0.4, 60, 80),
        ],
    )


class StabilityTests(unittest.TestCase):
    def test_analysis_report_keeps_stable_root_structure(self):
        report = AnalysisEngine().run(sample_request())

        self.assertEqual(report.decision.cell_id, "root.decision")
        self.assertEqual(report.summary, report.decision.explanation)
        self.assertTrue(report.schema_version)
        self.assertTrue(report.engine_version)
        self.assertTrue(report.formula_versions)
        self.assertGreaterEqual(len(report.decision.children), 6)

    def test_all_registered_cells_return_normalized_cell_result(self):
        request = sample_request()

        registry = default_registry()
        leaf_cell_ids = [
            node.cell_id
            for node in default_analysis_graph().nodes
            if node.execution_role == "leaf"
        ]

        for cell_id in leaf_cell_ids:
            cell = registry.resolve(cell_id)
            with self.subTest(cell_id=cell.cell_id):
                result = cell.analyze(request)
                self.assertIsInstance(result, CellResult)
                self.assertEqual(result.cell_id, cell.cell_id)
                self.assertEqual(result.target, request.target)
                self.assertEqual(result.horizon, request.horizon)
                self.assertIn(result.direction, {"bullish", "bearish", "neutral", "conflict"})
                self.assertGreaterEqual(result.strength, 0)
                self.assertLessEqual(result.strength, 100)
                self.assertGreaterEqual(result.confidence, 0)
                self.assertLessEqual(result.confidence, 100)
                self.assertGreaterEqual(result.volatility_risk, 0)
                self.assertLessEqual(result.volatility_risk, 100)
                self.assertGreaterEqual(result.manipulation_risk, 0)
                self.assertLessEqual(result.manipulation_risk, 100)
                self.assertIsInstance(result.evidence, list)
                self.assertIsInstance(result.metadata, dict)

    def test_decision_exposes_structured_risk_explanation(self):
        report = AnalysisEngine().run(sample_request())

        self.assertIn(report.decision.risk_level, {"low", "medium", "high", "extreme"})
        self.assertIn(
            report.decision.action_posture,
            {"observe", "wait_for_confirmation", "cautious_follow", "reduce_exposure", "avoid_chasing"},
        )
        self.assertIn("risk_breakdown", report.decision.metadata)
        self.assertIn("risk_notes", report.decision.metadata)
        self.assertIn("风险等级", report.decision.explanation)


if __name__ == "__main__":
    unittest.main()
