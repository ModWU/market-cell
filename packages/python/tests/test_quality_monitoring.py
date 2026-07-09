import unittest

from market_cell.data import (
    CandleBatch,
    CandleQuery,
    SourceProfile,
    SourceQualityMonitor,
)
from market_cell.models import Candle


class QualityMonitoringTests(unittest.TestCase):
    def test_monitor_accepts_clean_batch(self):
        report = SourceQualityMonitor().inspect_batch(_batch([100, 101, 102]))

        self.assertTrue(report.is_usable)
        self.assertEqual(report.issues, [])
        self.assertEqual(report.quality_score, 100)

    def test_monitor_detects_time_gap(self):
        batch = _batch(
            [100, 101, 102],
            timestamps=[
                "2026-07-09T00:00:00Z",
                "2026-07-09T01:00:00Z",
                "2026-07-09T03:00:00Z",
            ],
        )

        report = SourceQualityMonitor().inspect_batch(batch)

        self.assertTrue(report.is_usable)
        self.assertIn("time_gap", [issue.code for issue in report.issues])

    def test_monitor_detects_stale_data(self):
        batch = _batch(
            [100, 101, 102],
            timestamps=[
                "2026-07-09T00:00:00Z",
                "2026-07-09T01:00:00Z",
                "2026-07-09T02:00:00Z",
            ],
        )

        report = SourceQualityMonitor(stale_after_ms=3_600_000).inspect_batch(
            batch,
            now="2026-07-09T05:30:00Z",
        )

        self.assertIn("stale_data", [issue.code for issue in report.issues])

    def test_monitor_detects_volume_and_range_spikes(self):
        batch = CandleBatch(
            query=CandleQuery(symbol="BTC/USD", horizon="1h"),
            source=SourceProfile(provider="source_a", tier="professional", description="test"),
            candles=[
                Candle("2026-07-09T00:00:00Z", 100, 101, 99, 100, 100),
                Candle("2026-07-09T01:00:00Z", 100, 101, 99, 100, 110),
                Candle("2026-07-09T02:00:00Z", 100, 150, 80, 120, 2000),
            ],
        )

        report = SourceQualityMonitor(volume_spike_threshold=8, range_spike_threshold=5).inspect_batch(batch)
        codes = [issue.code for issue in report.issues]

        self.assertIn("volume_spike", codes)
        self.assertIn("range_spike", codes)

    def test_monitor_marks_invalid_ohlcv_as_unusable(self):
        report = SourceQualityMonitor().inspect_batch(
            CandleBatch(
                query=CandleQuery(symbol="BTC/USD", horizon="1h"),
                source=SourceProfile(provider="source_a", tier="professional", description="test"),
                candles=[Candle("2026-07-09T00:00:00Z", 100, 99, 101, 100, 100)],
            )
        )

        self.assertFalse(report.is_usable)
        self.assertIn("invalid_ohlcv", [issue.code for issue in report.issues])

    def test_monitor_reports_invalid_timestamp_without_crashing(self):
        report = SourceQualityMonitor().inspect_batch(
            _batch([100, 101], timestamps=["2026-07-09T00:00:00Z", "not-a-time"])
        )

        self.assertFalse(report.is_usable)
        self.assertIn("invalid_timestamp", [issue.code for issue in report.issues])

    def test_monitor_compares_close_deviation_between_sources(self):
        primary = _batch([100, 115], provider="primary")
        reference = _batch([100, 100], provider="reference")

        report = SourceQualityMonitor(cross_source_deviation_pct=2).compare_sources(primary, reference)

        self.assertTrue(report.is_usable)
        self.assertGreater(report.max_close_deviation_pct, 10)
        self.assertIn("cross_source_close_deviation", [issue.code for issue in report.issues])


def _batch(
    closes: list[float],
    provider: str = "source_a",
    timestamps: list[str] | None = None,
) -> CandleBatch:
    default_timestamps = [
        "2026-07-09T00:00:00Z",
        "2026-07-09T01:00:00Z",
        "2026-07-09T02:00:00Z",
        "2026-07-09T03:00:00Z",
    ]
    selected_timestamps = timestamps or default_timestamps[: len(closes)]
    candles = [
        Candle(timestamp, close - 1, close + 1, close - 2, close, 100 + index)
        for index, (timestamp, close) in enumerate(zip(selected_timestamps, closes))
    ]
    return CandleBatch(
        query=CandleQuery(symbol="BTC/USD", horizon="1h"),
        source=SourceProfile(provider=provider, tier="professional", description="test"),
        candles=candles,
    )


if __name__ == "__main__":
    unittest.main()
