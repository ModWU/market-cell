import tempfile
import unittest
from pathlib import Path

from market_cell.engine import AnalysisEngine
from market_cell.models import AnalysisRequest, Candle
from market_cell.replay import ReplayRunner, compare_formula_versions
from market_cell.reports import FileSystemReportStore


class ReplayRunnerTests(unittest.TestCase):
    def test_replay_reruns_saved_input_snapshot_and_compares_decision(self):
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", 100, 102, 99, 101, 1000),
                Candle("t2", 101, 104, 100, 103, 1200),
                Candle("t3", 103, 106, 102, 105, 1400),
                Candle("t4", 105, 108, 104, 107, 2200),
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(report_store=store).run(request)

            comparison = ReplayRunner(store).replay(report.report_id or "")

        self.assertTrue(comparison.input_hash_matches)
        self.assertTrue(comparison.result_stable)
        self.assertEqual(comparison.drift_fields, [])
        self.assertEqual(comparison.formula_version_changes, {})
        self.assertEqual(comparison.original_decision["direction"], comparison.replayed_decision["direction"])
        self.assertEqual(comparison.to_dict()["report_id"], report.report_id)

    def test_formula_version_comparison_reports_added_removed_and_changed_cells(self):
        changes = compare_formula_versions(
            {"trend": "v1", "volume": "v1", "removed": "v1"},
            {"trend": "v2", "volume": "v1", "added": "v1"},
        )

        self.assertEqual(changes["trend"], {"old": "v1", "new": "v2"})
        self.assertEqual(changes["removed"], {"old": "v1", "new": None})
        self.assertEqual(changes["added"], {"old": None, "new": "v1"})
        self.assertNotIn("volume", changes)


if __name__ == "__main__":
    unittest.main()
