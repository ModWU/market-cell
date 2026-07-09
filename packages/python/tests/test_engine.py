import unittest

from market_cell.engine import AnalysisEngine
from market_cell.models import AnalysisRequest, Candle, MarketEvent


class EngineTests(unittest.TestCase):
    def test_engine_returns_decision_report(self):
        request = AnalysisRequest(
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

        report = AnalysisEngine().run(request)

        self.assertEqual(report.target, "BTC/USD")
        self.assertEqual(report.decision.cell_id, "root.decision")
        self.assertIsNotNone(report.run_id)
        self.assertEqual(report.report_id, report.run_id)
        self.assertEqual(report.schema_version, "analysis_report.v1")
        self.assertEqual(report.engine_version, "0.1.0")
        self.assertIn("root.decision", report.formula_versions)
        self.assertIsNotNone(report.created_at)
        self.assertGreaterEqual(len(report.decision.children), 5)
        self.assertIn(report.decision.direction, {"bullish", "bearish", "neutral", "conflict"})


if __name__ == "__main__":
    unittest.main()
