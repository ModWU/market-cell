from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

from market_cell.engine import AnalysisEngine
from market_cell.graph import default_analysis_graph
from market_cell.models import AnalysisRequest, Candle
from market_cell.replay import (
    ReplayRunner,
    compare_formula_versions,
    compare_graph_definitions,
)
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
        self.assertEqual(comparison.graph_definition_changes, {})
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

    def test_replay_reports_graph_version_drift_separately_from_result_drift(self):
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", 100, 102, 99, 101, 1000),
                Candle("t2", 101, 104, 100, 103, 1200),
            ],
        )
        changed_graph = replace(
            default_analysis_graph(),
            graph_version="0.2.0",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(report_store=store).run(request)
            comparison = ReplayRunner(
                store,
                engine_factory=lambda: AnalysisEngine(
                    graph_definition=changed_graph,
                ),
            ).replay(report.report_id or "")

        self.assertTrue(comparison.result_stable)
        self.assertEqual(
            comparison.graph_definition_changes["graph_version"],
            {"old": "0.1.0", "new": "0.2.0"},
        )

    def test_graph_definition_comparison_reports_identity_changes(self):
        changes = compare_graph_definitions(
            {
                "graph_id": "graph.old",
                "graph_version": "1.0.0",
                "schema_version": "cell_graph_definition.v1",
            },
            {
                "graph_id": "graph.new",
                "graph_version": "2.0.0",
                "schema_version": "cell_graph_definition.v1",
            },
        )

        self.assertEqual(
            changes,
            {
                "graph_id": {"old": "graph.old", "new": "graph.new"},
                "graph_version": {"old": "1.0.0", "new": "2.0.0"},
            },
        )

    def test_graph_definition_comparison_detects_unversioned_content_drift(self):
        graph = default_analysis_graph().to_dict()
        changed = {
            **graph,
            "description": "changed without a graph version bump",
        }

        changes = compare_graph_definitions(graph, changed)

        self.assertEqual(set(changes), {"content_hash"})
        self.assertNotEqual(
            changes["content_hash"]["old"],
            changes["content_hash"]["new"],
        )


if __name__ == "__main__":
    unittest.main()
