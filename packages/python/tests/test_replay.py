from dataclasses import replace
import json
import tempfile
import unittest
from pathlib import Path

from market_cell.engine import AnalysisEngine
from market_cell.graph import default_analysis_graph
from market_cell.models import AnalysisRequest, Candle
from market_cell.replay import (
    ReplayRunner,
    compare_decision_trees,
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
        self.assertTrue(comparison.decision_tree_stable)
        self.assertEqual(comparison.decision_tree_drift_paths, [])
        self.assertEqual(
            comparison.original_decision_tree_hash,
            comparison.replayed_decision_tree_hash,
        )
        self.assertEqual(comparison.formula_version_changes, {})
        self.assertEqual(comparison.graph_definition_changes, {})
        self.assertEqual(comparison.original_decision["direction"], comparison.replayed_decision["direction"])
        self.assertEqual(comparison.to_dict()["report_id"], report.report_id)
        self.assertEqual(comparison.schema_version, "replay_comparison.v1")

    def test_replay_remains_compatible_with_legacy_analysis_run_v1(self):
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", 100, 102, 99, 101, 1000),
                Candle("t2", 101, 104, 100, 103, 1200),
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = FileSystemReportStore(root)
            report = AnalysisEngine(report_store=store).run(request)
            run_path = root / "runs" / f"{report.run_id}.json"
            legacy_run = json.loads(run_path.read_text(encoding="utf-8"))
            legacy_run["schema_version"] = "analysis_run.v1"
            legacy_run.pop("input_snapshots")
            legacy_run["metadata"].pop("input_snapshot_audits", None)
            run_path.write_text(
                json.dumps(legacy_run, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            comparison = ReplayRunner(store).replay(report.report_id or "")

        self.assertTrue(comparison.input_hash_matches)
        self.assertTrue(comparison.result_stable)

    def test_formula_version_comparison_reports_added_removed_and_changed_cells(self):
        changes = compare_formula_versions(
            {"trend": "v1", "volume": "v1", "removed": "v1"},
            {"trend": "v2", "volume": "v1", "added": "v1"},
        )

        self.assertEqual(changes["trend"], {"old": "v1", "new": "v2"})
        self.assertEqual(changes["removed"], {"old": "v1", "new": None})
        self.assertEqual(changes["added"], {"old": None, "new": "v1"})
        self.assertNotIn("volume", changes)

    def test_replay_detects_nested_decision_tree_drift_when_root_summary_matches(self):
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
            root = Path(temp_dir)
            store = FileSystemReportStore(root)
            report = AnalysisEngine(report_store=store).run(request)
            report_path = root / "reports" / f"{report.report_id}.json"
            stored_report = json.loads(report_path.read_text(encoding="utf-8"))
            stored_report["decision"]["children"][0]["metadata"][
                "unversioned_probe"
            ] = "tampered"
            report_path.write_text(
                json.dumps(stored_report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            comparison = ReplayRunner(store).replay(report.report_id or "")

        self.assertFalse(comparison.result_stable)
        self.assertFalse(comparison.decision_tree_stable)
        self.assertEqual(comparison.drift_fields, ["decision_tree"])
        self.assertIn(
            "decision.children[0].metadata.unversioned_probe:missing_replayed",
            comparison.decision_tree_drift_paths,
        )
        self.assertNotEqual(
            comparison.original_decision_tree_hash,
            comparison.replayed_decision_tree_hash,
        )
        self.assertEqual(comparison.formula_version_changes, {})
        self.assertEqual(comparison.graph_definition_changes, {})

    def test_decision_tree_comparison_uses_numeric_tolerance_and_rejects_invalid_tolerance(self):
        self.assertEqual(
            compare_decision_trees(
                {"score": 1.0, "children": [{"strength": 2.0}]},
                {"score": 1.0 + 1e-10, "children": [{"strength": 2.0}]},
            ),
            [],
        )
        self.assertEqual(
            compare_decision_trees(
                {"score": 1.0},
                {"score": 1.01},
                numeric_tolerance=1e-3,
            ),
            ["decision.score"],
        )
        with self.assertRaisesRegex(ValueError, "must not be negative"):
            compare_decision_trees({}, {}, numeric_tolerance=-1)

    def test_replay_reports_graph_version_drift_separately_from_result_drift(self):
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", 100, 102, 99, 101, 1000),
                Candle("t2", 101, 104, 100, 103, 1200),
            ],
        )
        current_graph = default_analysis_graph()
        changed_version = "999.0.0"
        changed_graph = replace(
            current_graph,
            graph_version=changed_version,
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
            {"old": current_graph.graph_version, "new": changed_version},
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
