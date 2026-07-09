import tempfile
import unittest
from pathlib import Path

from market_cell.data import CandleBatch, CandleQuery, CandleSourceError, FileCandleSource, MarketDataRouter
from market_cell.data.binance import normalize_binance_symbol, parse_binance_kline
from market_cell.data.quality import inspect_candles
from market_cell.models import Candle


class DataSourceTests(unittest.TestCase):
    def test_file_candle_source_reads_local_json(self):
        source = FileCandleSource(Path("examples/btc_usd_sample.json"))

        batch = source.fetch_candles(CandleQuery(symbol="BTC/USD", horizon="1h", limit=2))

        self.assertEqual(batch.source.provider, "local_json")
        self.assertEqual(len(batch.candles), 2)
        self.assertEqual(batch.candles[-1].close, 111600)

    def test_market_data_router_falls_back_to_next_source(self):
        class EmptySource:
            profile = FileCandleSource.profile

            def fetch_candles(self, query):
                return CandleBatch(query=query, candles=[], source=self.profile)

        router = MarketDataRouter(
            [
                EmptySource(),
                FileCandleSource(Path("examples/btc_usd_sample.json")),
            ]
        )

        batch = router.fetch_candles(CandleQuery(symbol="BTC/USD", horizon="1h", limit=1))

        self.assertEqual(len(batch.candles), 1)

    def test_market_data_router_reports_all_failures(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.json"
            router = MarketDataRouter([FileCandleSource(missing)])

            with self.assertRaises(CandleSourceError):
                router.fetch_candles(CandleQuery(symbol="BTC/USD", horizon="1h"))

    def test_market_data_router_rejects_low_quality_source(self):
        class InvalidSource:
            profile = FileCandleSource.profile

            def fetch_candles(self, query):
                return CandleBatch(
                    query=query,
                    source=self.profile,
                    candles=[
                        Candle("t1", open=100, high=99, low=101, close=100, volume=1000),
                    ],
                )

        router = MarketDataRouter(
            [
                InvalidSource(),
                FileCandleSource(Path("examples/btc_usd_sample.json")),
            ]
        )

        batch = router.fetch_candles(CandleQuery(symbol="BTC/USD", horizon="1h", limit=1))

        self.assertEqual(batch.source.provider, "local_json")

    def test_candle_quality_detects_duplicate_timestamps(self):
        report = inspect_candles(
            [
                Candle("t1", open=100, high=101, low=99, close=100, volume=1000),
                Candle("t1", open=100, high=101, low=99, close=100, volume=1000),
            ]
        )

        self.assertFalse(report.is_usable)
        self.assertTrue(any("duplicate" in issue for issue in report.issues))

    def test_binance_kline_parser(self):
        candle = parse_binance_kline([1720000000000, "100", "105", "99", "103", "12.5"])

        self.assertEqual(candle.timestamp, "1720000000000")
        self.assertEqual(candle.high, 105)
        self.assertEqual(candle.volume, 12.5)

    def test_binance_symbol_normalization(self):
        self.assertEqual(normalize_binance_symbol("BTC/USDT"), "BTCUSDT")
        self.assertEqual(normalize_binance_symbol("BTC-USDT"), "BTCUSDT")


if __name__ == "__main__":
    unittest.main()
