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
    rank_source_health,
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


if __name__ == "__main__":
    unittest.main()
