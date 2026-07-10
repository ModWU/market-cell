import json
import unittest
from pathlib import Path
import tempfile

from market_cell.engine import AnalysisEngine
from market_cell.execution import build_local_execution_plan
from market_cell.models import AnalysisRequest, Candle
from market_cell.registry import default_registry
from market_cell.reports import FileSystemReportStore


ROOT = Path(__file__).resolve().parents[3]


class ContractTests(unittest.TestCase):
    def test_json_contracts_are_valid_json(self):
        contract_paths = sorted((ROOT / "contracts" / "json_schema").glob("*.schema.json"))

        self.assertGreaterEqual(len(contract_paths), 2)
        for path in contract_paths:
            with self.subTest(path=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertIn("title", data)

    def test_market_data_contracts_exist_for_realtime_and_batch_paths(self):
        proto = (ROOT / "contracts" / "protobuf" / "market_data.proto").read_text(encoding="utf-8")
        parquet = (ROOT / "contracts" / "parquet" / "candle_schema.md").read_text(encoding="utf-8")

        self.assertIn("package market_cell.market_data.v1", proto)
        self.assertIn("message MarketDataEvent", proto)
        self.assertIn("message CandleClosed", proto)
        self.assertIn("source_provider", parquet)
        self.assertIn("quality_flags", parquet)

    def test_analysis_report_contains_contract_required_fields(self):
        schema = json.loads(
            (ROOT / "contracts" / "json_schema" / "analysis_report.schema.json").read_text(encoding="utf-8")
        )
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", open=100, high=101, low=99, close=100, volume=1000),
                Candle("t2", open=100, high=102, low=99, close=101, volume=1200),
            ],
        )

        report = AnalysisEngine().run(request).to_dict()

        for field_name in schema["required"]:
            with self.subTest(field_name=field_name):
                self.assertIn(field_name, report)

    def test_analysis_run_contains_contract_required_fields(self):
        schema = json.loads(
            (ROOT / "contracts" / "json_schema" / "analysis_run.schema.json").read_text(encoding="utf-8")
        )
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", open=100, high=101, low=99, close=100, volume=1000),
                Candle("t2", open=100, high=102, low=99, close=101, volume=1200),
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(report_store=store).run(request)
            run = store.load_run(report.run_id or "")

        for field_name in schema["required"]:
            with self.subTest(field_name=field_name):
                self.assertIn(field_name, run)
        self.assertEqual(run["schema_version"], "analysis_run.v1")

    def test_cell_execution_plan_contains_contract_required_fields(self):
        schema = json.loads(
            (ROOT / "contracts" / "json_schema" / "cell_execution_plan.schema.json").read_text(encoding="utf-8")
        )
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", open=100, high=101, low=99, close=100, volume=1000),
                Candle("t2", open=100, high=102, low=99, close=101, volume=1200),
            ],
        )

        plan = build_local_execution_plan(default_registry(), request).to_dict()

        for field_name in schema["required"]:
            with self.subTest(field_name=field_name):
                self.assertIn(field_name, plan)
        self.assertEqual(plan["schema_version"], "cell_execution_plan.v1")
        self.assertTrue(plan["service_bindings"])

    def test_cell_runtime_trace_contains_contract_required_fields(self):
        schema = json.loads(
            (ROOT / "contracts" / "json_schema" / "cell_runtime_trace.schema.json").read_text(encoding="utf-8")
        )
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", open=100, high=101, low=99, close=100, volume=1000),
                Candle("t2", open=100, high=102, low=99, close=101, volume=1200),
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(report_store=store).run(request)
            run = store.load_run(report.run_id or "")
            trace = run["metadata"]["cell_runtime_traces"][0]

        for field_name in schema["required"]:
            with self.subTest(field_name=field_name):
                self.assertIn(field_name, trace)
        self.assertEqual(trace["schema_version"], "cell_runtime_trace.v1")

    def test_cell_runtime_summary_contains_contract_required_fields(self):
        schema = json.loads(
            (ROOT / "contracts" / "json_schema" / "cell_runtime_summary.schema.json").read_text(encoding="utf-8")
        )
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", open=100, high=101, low=99, close=100, volume=1000),
                Candle("t2", open=100, high=102, low=99, close=101, volume=1200),
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(report_store=store).run(request)
            run = store.load_run(report.run_id or "")
            summary = run["metadata"]["cell_runtime_summaries"][0]

        for field_name in schema["required"]:
            with self.subTest(field_name=field_name):
                self.assertIn(field_name, summary)
        self.assertEqual(summary["schema_version"], "cell_runtime_summary.v1")


if __name__ == "__main__":
    unittest.main()
