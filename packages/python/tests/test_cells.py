import unittest

from market_cell.cells.risk import ManipulationRiskCell
from market_cell.models import AnalysisRequest, Candle


class CellTests(unittest.TestCase):
    def test_manipulation_cell_detects_volume_and_wick_risk(self):
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", 100, 101, 99, 100, 1000),
                Candle("t2", 100, 101, 99, 100, 1050),
                Candle("t3", 100, 101, 99, 100, 980),
                Candle("t4", 100, 120, 96, 101, 5000),
            ],
        )

        result = ManipulationRiskCell().analyze(request)

        self.assertGreater(result.manipulation_risk, 35)
        self.assertEqual(result.direction, "conflict")
        self.assertGreaterEqual(len(result.evidence), 2)


if __name__ == "__main__":
    unittest.main()
