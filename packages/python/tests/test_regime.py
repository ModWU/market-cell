import unittest

from market_cell.cells.regime import MarketRegimeCell
from market_cell.models import AnalysisRequest, Candle


class MarketRegimeTests(unittest.TestCase):
    def test_regime_cell_detects_range_market(self):
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", 100, 101, 99, 100, 1000),
                Candle("t2", 100, 101, 99, 100.5, 1000),
                Candle("t3", 100.5, 101, 99.5, 100.1, 1000),
                Candle("t4", 100.1, 101, 99.2, 100.2, 1000),
            ],
        )

        result = MarketRegimeCell().analyze(request)

        self.assertEqual(result.metadata["market_regime"], "range")
        self.assertEqual(result.direction, "neutral")

    def test_regime_cell_caps_trend_efficiency(self):
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", 100, 102, 99, 101, 1000),
                Candle("t2", 101, 104, 100, 103, 1000),
                Candle("t3", 103, 106, 102, 105, 1000),
                Candle("t4", 105, 109, 104, 108, 1000),
            ],
        )

        result = MarketRegimeCell().analyze(request)

        self.assertLessEqual(result.metadata["trend_efficiency"], 1.0)


if __name__ == "__main__":
    unittest.main()
