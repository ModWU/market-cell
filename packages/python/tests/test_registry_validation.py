import unittest

from market_cell.engine import AnalysisEngine
from market_cell.models import AnalysisRequest, Candle, MarketEvent
from market_cell.registry import default_registry
from market_cell.validation import ValidationError


class RegistryValidationTests(unittest.TestCase):
    def test_registry_exposes_cell_manifests(self):
        manifests = default_registry().manifests()

        self.assertGreaterEqual(len(manifests), 6)
        self.assertTrue(all(manifest.cell_id for manifest in manifests))
        self.assertTrue(all(manifest.formula_version for manifest in manifests))

    def test_engine_rejects_invalid_candle_shape(self):
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", open=100, high=99, low=95, close=98, volume=1000),
            ],
        )

        with self.assertRaises(ValidationError):
            AnalysisEngine().run(request)

    def test_engine_rejects_invalid_event_range(self):
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", open=100, high=101, low=99, close=100, volume=1000),
            ],
            events=[
                MarketEvent("bad event", "news", sentiment=1.5, impact=20, freshness=80),
            ],
        )

        with self.assertRaises(ValidationError):
            AnalysisEngine().run(request)

    def test_engine_rejects_duplicate_candle_timestamps(self):
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", open=100, high=101, low=99, close=100, volume=1000),
                Candle("t1", open=100, high=101, low=99, close=100, volume=1000),
            ],
        )

        with self.assertRaises(ValidationError):
            AnalysisEngine().run(request)


if __name__ == "__main__":
    unittest.main()
