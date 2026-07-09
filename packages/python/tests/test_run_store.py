import tempfile
import unittest
from pathlib import Path

from market_cell.engine import AnalysisEngine
from market_cell.events import EventBus
from market_cell.models import AnalysisRequest, Candle
from market_cell.reports import FileSystemReportStore


class RunStoreTests(unittest.TestCase):
    def test_engine_can_save_report_and_run_metadata(self):
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
            event_bus = EventBus()

            report = AnalysisEngine(event_bus=event_bus, report_store=store).run(request)
            saved_report = store.load_report(report.report_id or "")
            saved_run = store.load_run(report.run_id or "")

        self.assertEqual(saved_report["target"], "BTC/USD")
        self.assertEqual(saved_run["status"], "succeeded")
        self.assertEqual(saved_run["report_id"], report.report_id)
        self.assertTrue(saved_run["formula_versions"])
        self.assertIn("analysis.started", [event.name for event in event_bus.events])
        self.assertIn("analysis.saved", [event.name for event in event_bus.events])
        self.assertIn("analysis.completed", [event.name for event in event_bus.events])

    def test_engine_persists_runtime_metadata(self):
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
            report = AnalysisEngine(
                report_store=store,
                run_metadata={"data_sources": {"router_plan": {"entries": []}}},
            ).run(
                request,
                metadata={"data_quality": {"score": 98}},
            )
            saved_run = store.load_run(report.run_id or "")

        self.assertEqual(saved_run["metadata"]["data_sources"]["router_plan"]["entries"], [])
        self.assertEqual(saved_run["metadata"]["data_quality"]["score"], 98)

    def test_report_store_lists_saved_reports(self):
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

            report_ids = store.list_reports()

        self.assertEqual(report_ids, [report.report_id])


if __name__ == "__main__":
    unittest.main()
