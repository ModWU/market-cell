import tempfile
import unittest
from pathlib import Path

from market_cell.data import (
    CandleBatch,
    CandleQuery,
    DataQualityIssue,
    DataQualityRecord,
    FileSystemDataQualityStore,
    SourceProfile,
    SourceQualityMonitor,
    build_health_trends,
    rank_provider_reliability,
    rank_source_health,
    summarize_provider_reliability,
    summarize_quality_records,
)
from market_cell.models import Candle


class SourceHealthTests(unittest.TestCase):
    def test_summarizes_quality_records_by_provider_symbol_and_horizon(self):
        records = [
            _record("source_a", "BTC/USD", "1h", "time_gap", "warning", "2026-07-09T00:00:00Z"),
            _record("source_a", "BTC/USD", "1h", "stale_data", "warning", "2026-07-09T01:00:00Z"),
            _record("source_b", "BTC/USD", "1h", "invalid_ohlcv", "critical", "2026-07-09T00:30:00Z"),
        ]

        summaries = summarize_quality_records(records)

        self.assertEqual(len(summaries), 2)
        source_a = next(item for item in summaries if item.source_provider == "source_a")
        source_b = next(item for item in summaries if item.source_provider == "source_b")
        self.assertEqual(source_a.record_count, 2)
        self.assertEqual(source_a.health_score, 90)
        self.assertEqual(source_a.health_grade, "good")
        self.assertEqual(source_a.severity_counts, {"warning": 2})
        self.assertEqual(source_a.issue_counts, {"stale_data": 1, "time_gap": 1})
        self.assertEqual(source_a.first_observed_at, "2026-07-09T00:00:00Z")
        self.assertEqual(source_a.last_observed_at, "2026-07-09T01:00:00Z")
        self.assertEqual(source_b.health_score, 80)
        self.assertEqual(source_b.health_grade, "degraded")

    def test_ranks_healthiest_sources_first(self):
        summaries = summarize_quality_records(
            [
                _record("source_a", "BTC/USD", "1h", "time_gap", "warning", "2026-07-09T00:00:00Z"),
                _record("source_b", "BTC/USD", "1h", "invalid_ohlcv", "critical", "2026-07-09T00:00:00Z"),
                _record("source_c", "BTC/USD", "1h", "metadata_note", "info", "2026-07-09T00:00:00Z"),
            ]
        )

        ranked = rank_source_health(summaries)

        self.assertEqual([item.source_provider for item in ranked], ["source_c", "source_a", "source_b"])

    def test_store_can_summarize_persisted_records(self):
        report = SourceQualityMonitor().inspect_batch(
            CandleBatch(
                query=CandleQuery(symbol="BTC/USD", horizon="1h"),
                source=SourceProfile(provider="source_a", tier="professional", description="test"),
                candles=[
                    Candle("2026-07-09T00:00:00Z", 100, 101, 99, 100, 100),
                    Candle("2026-07-09T02:00:00Z", 100, 101, 99, 100, 120),
                ],
            )
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemDataQualityStore(Path(temp_dir))
            store.save_source_report(report, observed_at="2026-07-09T03:00:00Z")
            summaries = store.summarize(source_provider="source_a", symbol="BTC/USD", horizon="1h")

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].source_provider, "source_a")
        self.assertEqual(summaries[0].issue_counts, {"time_gap": 1})

    def test_builds_daily_health_trends(self):
        records = [
            _record("source_a", "BTC/USD", "1h", "time_gap", "warning", "2026-07-09T00:00:00Z"),
            _record("source_a", "BTC/USD", "1h", "stale_data", "warning", "2026-07-09T12:00:00Z"),
            _record("source_a", "BTC/USD", "1h", "invalid_ohlcv", "critical", "2026-07-10T00:00:00Z"),
        ]

        trends = build_health_trends(records, window="day")

        self.assertEqual(len(trends), 2)
        self.assertEqual(trends[0].window_start, "2026-07-09")
        self.assertEqual(trends[0].record_count, 2)
        self.assertEqual(trends[0].health_score, 90)
        self.assertEqual(trends[1].window_start, "2026-07-10")
        self.assertEqual(trends[1].health_score, 80)

    def test_builds_hourly_health_trends(self):
        records = [
            _record("source_a", "BTC/USD", "1h", "time_gap", "warning", "2026-07-09T00:15:00Z"),
            _record("source_a", "BTC/USD", "1h", "stale_data", "warning", "2026-07-09T00:45:00Z"),
            _record("source_a", "BTC/USD", "1h", "invalid_ohlcv", "critical", "2026-07-09T01:00:00Z"),
        ]

        trends = build_health_trends(records, window="hour")

        self.assertEqual([trend.window_start for trend in trends], ["2026-07-09T00:00:00Z", "2026-07-09T01:00:00Z"])
        self.assertEqual([trend.health_score for trend in trends], [90, 80])

    def test_rejects_unknown_trend_window(self):
        with self.assertRaises(ValueError):
            build_health_trends([], window="week")

    def test_summarizes_provider_reliability_from_trends(self):
        records = [
            _record("source_a", "BTC/USD", "1h", "time_gap", "warning", "2026-07-09T00:00:00Z"),
            _record("source_a", "ETH/USD", "1h", "stale_data", "warning", "2026-07-10T00:00:00Z"),
            _record("source_b", "BTC/USD", "1h", "invalid_ohlcv", "critical", "2026-07-09T00:00:00Z"),
            _record("source_b", "BTC/USD", "1h", "time_gap", "warning", "2026-07-10T00:00:00Z"),
        ]

        reliability = summarize_provider_reliability(records, window="day")
        ranked = rank_provider_reliability(reliability)

        self.assertEqual([item.source_provider for item in ranked], ["source_a", "source_b"])
        source_a = ranked[0]
        self.assertEqual(source_a.trend_point_count, 2)
        self.assertEqual(source_a.record_count, 2)
        self.assertEqual(source_a.average_health_score, 95)
        self.assertEqual(source_a.latest_health_score, 95)
        self.assertEqual(source_a.worst_health_score, 95)
        self.assertEqual(source_a.health_grade, "excellent")
        self.assertEqual(source_a.affected_symbols, ["BTC/USD", "ETH/USD"])

    def test_store_can_build_health_trends_and_provider_reliability(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemDataQualityStore(Path(temp_dir))
            store.save_issue(
                _issue("source_a", "BTC/USD", "1h", "time_gap", "warning"),
                observed_at="2026-07-09T00:00:00Z",
            )
            store.save_issue(
                _issue("source_a", "BTC/USD", "1h", "invalid_ohlcv", "critical"),
                observed_at="2026-07-10T00:00:00Z",
            )

            trends = store.health_trends(source_provider="source_a", symbol="BTC/USD", horizon="1h")
            reliability = store.provider_reliability(source_provider="source_a")

        self.assertEqual([trend.window_start for trend in trends], ["2026-07-09", "2026-07-10"])
        self.assertEqual(len(reliability), 1)
        self.assertEqual(reliability[0].source_provider, "source_a")
        self.assertEqual(reliability[0].worst_health_score, 80)


def _record(
    provider: str,
    symbol: str,
    horizon: str,
    code: str,
    severity: str,
    observed_at: str,
) -> DataQualityRecord:
    issue = DataQualityIssue(
        code=code,
        severity=severity,
        message=code,
        source_provider=provider,
        symbol=symbol,
        horizon=horizon,
    )
    return DataQualityRecord(
        record_id=f"{provider}-{code}-{observed_at}",
        kind="source_quality",
        observed_at=observed_at,
        issue=issue,
    )


def _issue(
    provider: str,
    symbol: str,
    horizon: str,
    code: str,
    severity: str,
) -> DataQualityIssue:
    return DataQualityIssue(
        code=code,
        severity=severity,
        message=code,
        source_provider=provider,
        symbol=symbol,
        horizon=horizon,
    )


if __name__ == "__main__":
    unittest.main()
