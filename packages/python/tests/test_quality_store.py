import tempfile
import unittest
from pathlib import Path

from market_cell.data import (
    CandleBatch,
    CandleQuery,
    FileSystemDataQualityStore,
    SourceProfile,
    SourceQualityMonitor,
)
from market_cell.models import Candle


class QualityStoreTests(unittest.TestCase):
    def test_store_persists_source_quality_report_as_jsonl_records(self):
        batch = CandleBatch(
            query=CandleQuery(symbol="BTC/USD", horizon="1h"),
            source=SourceProfile(provider="source_a", tier="professional", description="test"),
            candles=[
                Candle("2026-07-09T00:00:00Z", 100, 101, 99, 100, 100),
                Candle("2026-07-09T02:00:00Z", 100, 101, 99, 100, 120),
            ],
        )
        report = SourceQualityMonitor().inspect_batch(batch)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemDataQualityStore(Path(temp_dir))
            saved = store.save_source_report(report, observed_at="2026-07-09T03:00:00Z")
            records = store.list_records()

        self.assertEqual(len(saved), 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].issue.code, "time_gap")
        self.assertEqual(records[0].context["quality_score"], report.quality_score)
        self.assertEqual(records[0].kind, "source_quality")

    def test_store_filters_records_by_source_symbol_code_and_severity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemDataQualityStore(Path(temp_dir))
            issue_a = SourceQualityMonitor().inspect_batch(_batch("source_a", "BTC/USD")).issues[0]
            issue_b = SourceQualityMonitor().inspect_batch(_batch("source_b", "ETH/USD")).issues[0]
            store.save_issue(issue_a, observed_at="2026-07-09T03:00:00Z")
            store.save_issue(issue_b, observed_at="2026-07-09T03:00:00Z")

            filtered = store.list_records(source_provider="source_a", symbol="BTC/USD", code="time_gap", severity="warning")

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].issue.source_provider, "source_a")
        self.assertEqual(filtered[0].issue.symbol, "BTC/USD")

    def test_store_persists_cross_source_comparison_context(self):
        primary = _batch("primary", "BTC/USD", closes=[100, 115])
        reference = _batch("reference", "BTC/USD", closes=[100, 100])
        comparison = SourceQualityMonitor(cross_source_deviation_pct=2).compare_sources(primary, reference)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemDataQualityStore(Path(temp_dir))
            saved = store.save_comparison_report(comparison, observed_at="2026-07-09T03:00:00Z")
            records = store.list_records(code="cross_source_close_deviation")

        self.assertEqual(len(saved), 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].kind, "source_comparison")
        self.assertEqual(records[0].context["reference_provider"], "reference")
        self.assertGreater(records[0].context["max_close_deviation_pct"], 10)

    def test_store_returns_empty_list_when_root_does_not_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemDataQualityStore(Path(temp_dir) / "missing")

            self.assertEqual(store.list_records(), [])


def _batch(provider: str, symbol: str, closes: list[float] | None = None) -> CandleBatch:
    close_values = closes or [100, 101]
    timestamps = ["2026-07-09T00:00:00Z", "2026-07-09T02:00:00Z"]
    candles = [
        Candle(timestamp, close - 1, close + 1, close - 2, close, 100 + index)
        for index, (timestamp, close) in enumerate(zip(timestamps, close_values))
    ]
    return CandleBatch(
        query=CandleQuery(symbol=symbol, horizon="1h"),
        source=SourceProfile(provider=provider, tier="professional", description="test"),
        candles=candles,
    )


if __name__ == "__main__":
    unittest.main()
