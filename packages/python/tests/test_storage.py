import tempfile
import unittest
from pathlib import Path

from market_cell.data import (
    CANDLE_STORAGE_SCHEMA_VERSION,
    CandleBatch,
    CandleQuery,
    FileCandleSource,
    OptionalStorageDependencyError,
    SourceProfile,
    batch_to_candle_rows,
    interval_to_millis,
    partition_path,
    timestamp_to_ms,
)
from market_cell.data.storage import _require_optional_module
from market_cell.models import Candle


class StorageTests(unittest.TestCase):
    def test_batch_to_candle_rows_matches_parquet_contract_fields(self):
        batch = CandleBatch(
            query=CandleQuery(symbol="BTC/USDT", horizon="1h", venue="binance"),
            source=SourceProfile(
                provider="kaiko",
                tier="professional",
                description="test professional source",
            ),
            candles=[
                Candle(
                    timestamp="2026-07-09T00:00:00Z",
                    open=100,
                    high=105,
                    low=99,
                    close=103,
                    volume=12.5,
                )
            ],
            fetched_at="2026-07-09T00:01:00+00:00",
            metadata={"market_type": "spot", "quality_flags": ["cross_source_deviation"]},
        )

        rows = batch_to_candle_rows(batch)

        self.assertEqual(CANDLE_STORAGE_SCHEMA_VERSION, "candle_parquet.v0.1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source_provider, "kaiko")
        self.assertEqual(rows[0].exchange, "binance")
        self.assertEqual(rows[0].symbol, "BTC/USDT")
        self.assertEqual(rows[0].market_type, "spot")
        self.assertEqual(rows[0].interval, "1h")
        self.assertEqual(rows[0].open_time_ms, 1783555200000)
        self.assertEqual(rows[0].close_time_ms, 1783558799999)
        self.assertEqual(rows[0].fetched_at_ms, 1783555260000)
        self.assertEqual(rows[0].quality_flags, ["cross_source_deviation"])

    def test_partition_path_uses_stable_contract_layout(self):
        batch = FileCandleSource(Path("examples/btc_usd_sample.json")).fetch_candles(
            CandleQuery(symbol="BTC/USD", horizon="1h", limit=1, venue="coinbase")
        )
        row = batch_to_candle_rows(batch)[0]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = partition_path(temp_dir, row)

        self.assertIn("provider=local_json", str(path))
        self.assertIn("exchange=coinbase", str(path))
        self.assertIn("symbol=btc_usd", str(path))
        self.assertIn("interval=1h", str(path))
        self.assertIn("date=2026-07-09", str(path))

    def test_timestamp_and_interval_helpers_are_deterministic(self):
        self.assertEqual(timestamp_to_ms("1720000000000"), 1720000000000)
        self.assertEqual(timestamp_to_ms("1720000000"), 1720000000000)
        self.assertEqual(timestamp_to_ms("2026-07-09T00:00:00Z"), 1783555200000)
        self.assertEqual(interval_to_millis("1m"), 60_000)
        self.assertEqual(interval_to_millis("4h"), 14_400_000)
        self.assertEqual(interval_to_millis("1d"), 86_400_000)
        self.assertEqual(interval_to_millis("bad"), 0)

    def test_optional_storage_dependency_error_is_explicit(self):
        with self.assertRaises(OptionalStorageDependencyError) as context:
            _require_optional_module("market_cell_missing_optional_module", "missing-package")

        self.assertIn("missing-package", str(context.exception))


if __name__ == "__main__":
    unittest.main()
