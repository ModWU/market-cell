from dataclasses import replace
import json
import unittest
from pathlib import Path
import tempfile
from typing import get_args

from market_cell.engine import AnalysisEngine
from market_cell.execution import (
    ExecutionPlanValidationError,
    PlanValidationCode,
    build_local_capability_catalog,
    build_local_execution_plan,
    validate_execution_plan,
)
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
        self.assertEqual(plan["schema_version"], "cell_execution_plan.v2")
        self.assertTrue(all(node["binding_id"] for node in plan["nodes"]))
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

    def test_plan_execution_contains_contract_required_fields(self):
        schema = json.loads(
            (
                ROOT
                / "contracts"
                / "json_schema"
                / "plan_execution.schema.json"
            ).read_text(encoding="utf-8")
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(report_store=store).run(_request())
            run = store.load_run(report.run_id or "")
            execution = run["metadata"]["plan_execution"]

        for field_name in schema["required"]:
            with self.subTest(field_name=field_name):
                self.assertIn(field_name, execution)
        self.assertEqual(execution["schema_version"], "plan_execution.v1")
        self.assertEqual(execution["status"], "succeeded")

    def test_service_capability_catalog_contains_contract_required_fields(self):
        schema = json.loads(
            (
                ROOT
                / "contracts"
                / "json_schema"
                / "service_capability_catalog.schema.json"
            ).read_text(encoding="utf-8")
        )

        catalog = build_local_capability_catalog(default_registry()).to_dict()

        for field_name in schema["required"]:
            with self.subTest(field_name=field_name):
                self.assertIn(field_name, catalog)
        self.assertEqual(catalog["schema_version"], "service_capability_catalog.v2")
        self.assertTrue(catalog["bindings"])

    def test_cell_service_binding_contains_contract_required_fields(self):
        schema = json.loads(
            (
                ROOT
                / "contracts"
                / "json_schema"
                / "cell_service_binding.schema.json"
            ).read_text(encoding="utf-8")
        )
        binding = build_local_capability_catalog(default_registry()).to_dict()["bindings"][0]

        for field_name in schema["required"]:
            with self.subTest(field_name=field_name):
                self.assertIn(field_name, binding)

    def test_cell_placement_decision_contains_contract_required_fields(self):
        schema = json.loads(
            (
                ROOT
                / "contracts"
                / "json_schema"
                / "cell_placement_decision.schema.json"
            ).read_text(encoding="utf-8")
        )
        plan = build_local_execution_plan(default_registry(), _request()).to_dict()
        decision = plan["metadata"]["placement_decisions"][0]

        for field_name in schema["required"]:
            with self.subTest(field_name=field_name):
                self.assertIn(field_name, decision)
        self.assertEqual(decision["schema_version"], "cell_placement_decision.v2")
        self.assertTrue(decision["selected_binding_id"])

    def test_execution_plan_validation_contains_contract_required_fields(self):
        schema = json.loads(
            (
                ROOT
                / "contracts"
                / "json_schema"
                / "execution_plan_validation.schema.json"
            ).read_text(encoding="utf-8")
        )
        plan = build_local_execution_plan(default_registry(), _request())
        root = next(node for node in plan.nodes if node.node_id == plan.root_node_id)
        invalid_root = replace(root, dependencies=[*root.dependencies, "cell:missing"])
        invalid_plan = replace(
            plan,
            nodes=[invalid_root if node.node_id == root.node_id else node for node in plan.nodes],
        )

        with self.assertRaises(ExecutionPlanValidationError) as context:
            validate_execution_plan(invalid_plan)
        validation = context.exception.to_dict()

        for field_name in schema["required"]:
            with self.subTest(field_name=field_name):
                self.assertIn(field_name, validation)
        self.assertEqual(validation["schema_version"], "execution_plan_validation.v1")
        schema_codes = set(schema["$defs"]["issue"]["properties"]["code"]["enum"])
        self.assertEqual(schema_codes, set(get_args(PlanValidationCode)))


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        target="BTC/USD",
        horizon="1h",
        candles=[
            Candle("t1", open=100, high=101, low=99, close=100, volume=1000),
            Candle("t2", open=100, high=102, low=99, close=101, volume=1200),
        ],
    )


if __name__ == "__main__":
    unittest.main()
