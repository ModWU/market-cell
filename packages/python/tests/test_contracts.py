from dataclasses import replace
from datetime import timedelta
import json
import unittest
from pathlib import Path
import tempfile
from typing import get_args

from market_cell.engine import AnalysisEngine
from market_cell.data import FundingOpenInterestSnapshot, OrderBookSnapshot
from market_cell.execution import (
    ExecutionPlanValidationError,
    PlanValidationCode,
    RuntimeSummarySnapshot,
    RuntimeSummaryWriteRecord,
    build_local_capability_catalog,
    build_local_execution_plan,
    validate_execution_plan,
)
from market_cell.graph import (
    CellGraphValidationError,
    GraphValidationCode,
    default_analysis_graph,
    validate_cell_graph_definition,
)
from market_cell.hashing import stable_json_hash
from market_cell.features import build_feature_snapshot
from market_cell.inputs import (
    CellInputBundle,
    InputKind,
    InputResolutionRecord,
    InputSnapshot,
    ResolvedCellInput,
)
from market_cell.horizons import (
    HorizonAlignmentStatus,
    HorizonBand,
    HorizonConflictType,
    HorizonDecisionCell,
    MultiHorizonAnalyzer,
    MultiHorizonExecutionCode,
    MultiHorizonExecutionError,
    MultiHorizonRequest,
)
from market_cell.models import AnalysisRequest, Candle
from market_cell.performance import (
    DurationDistribution,
    NodePerformance,
    PerformanceBenchmarkResult,
    PerformanceThresholds,
    ReferenceMeasurement,
)
from market_cell.registry import default_registry
from market_cell.replay import ReplayRunner
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

    def test_local_schema_references_point_to_existing_contracts(self):
        schema_dir = ROOT / "contracts" / "json_schema"

        for path in sorted(schema_dir.glob("*.schema.json")):
            schema = json.loads(path.read_text(encoding="utf-8"))
            for reference in _schema_references(schema):
                with self.subTest(path=path.name, reference=reference):
                    target_name = reference.rsplit("/", 1)[-1]
                    self.assertTrue((schema_dir / target_name).is_file())

    def test_input_kind_enums_match_runtime_contract(self):
        schema_dir = ROOT / "contracts" / "json_schema"
        runtime_kinds = set(get_args(InputKind))
        schema_paths = {
            "input_snapshot.schema.json": ("properties", "input_kind", "enum"),
            "input_snapshot_audit.schema.json": (
                "properties",
                "input_kind",
                "enum",
            ),
            "input_reference.schema.json": (
                "properties",
                "input_kind",
                "enum",
            ),
            "input_resolution_record.schema.json": (
                "properties",
                "input_kind",
                "enum",
            ),
            "cell_input_bundle.schema.json": (
                "$defs",
                "input_kind",
                "enum",
            ),
            "cell_execution_plan.schema.json": (
                "$defs",
                "input_kind",
                "enum",
            ),
        }

        for name, path in schema_paths.items():
            schema = json.loads((schema_dir / name).read_text(encoding="utf-8"))
            value = schema
            for key in path:
                value = value[key]
            with self.subTest(schema=name):
                self.assertEqual(set(value), runtime_kinds)

    def test_input_identity_matches_shared_contract_vector(self):
        vector = json.loads(
            (
                ROOT
                / "contracts"
                / "test_vectors"
                / "input_identity_v1.json"
            ).read_text(encoding="utf-8")
        )
        snapshot = InputSnapshot.create(
            input_kind=vector["input_kind"],
            target=vector["target"],
            horizon=vector["horizon"],
            payload=vector["payload"],
            data_version=vector["data_version"],
            source=vector["source"],
        )

        self.assertEqual(snapshot.content_hash, vector["expected_content_hash"])
        self.assertEqual(
            snapshot.payload_size_bytes,
            vector["expected_payload_size_bytes"],
        )
        self.assertEqual(snapshot.snapshot_id, vector["expected_snapshot_id"])
        self.assertEqual(
            snapshot.to_reference().reference_id,
            vector["expected_reference_id"],
        )

    def test_order_book_identity_matches_shared_contract_vector(self):
        vector = json.loads(
            (
                ROOT
                / "contracts"
                / "test_vectors"
                / "order_book_snapshot_v1.json"
            ).read_text(encoding="utf-8")
        )
        order_book = OrderBookSnapshot.from_dict(vector["payload"])

        snapshot = order_book.to_input_snapshot(horizon=vector["horizon"])

        self.assertEqual(snapshot.input_kind, vector["input_kind"])
        self.assertEqual(snapshot.target, vector["target"])
        self.assertEqual(snapshot.data_version, vector["data_version"])
        self.assertEqual(snapshot.source, vector["source"])
        self.assertEqual(snapshot.content_hash, vector["expected_content_hash"])
        self.assertEqual(
            snapshot.payload_size_bytes,
            vector["expected_payload_size_bytes"],
        )
        self.assertEqual(snapshot.snapshot_id, vector["expected_snapshot_id"])
        self.assertEqual(
            snapshot.to_reference().reference_id,
            vector["expected_reference_id"],
        )

    def test_funding_open_interest_identity_matches_shared_contract_vector(self):
        vector = json.loads(
            (
                ROOT
                / "contracts"
                / "test_vectors"
                / "funding_open_interest_snapshot_v1.json"
            ).read_text(encoding="utf-8")
        )
        derivatives = FundingOpenInterestSnapshot.from_dict(vector["payload"])

        snapshot = derivatives.to_input_snapshot(horizon=vector["horizon"])

        self.assertEqual(snapshot.input_kind, vector["input_kind"])
        self.assertEqual(snapshot.target, vector["target"])
        self.assertEqual(snapshot.data_version, vector["data_version"])
        self.assertEqual(snapshot.source, vector["source"])
        self.assertEqual(snapshot.content_hash, vector["expected_content_hash"])
        self.assertEqual(
            snapshot.payload_size_bytes,
            vector["expected_payload_size_bytes"],
        )
        self.assertEqual(snapshot.snapshot_id, vector["expected_snapshot_id"])
        self.assertEqual(
            snapshot.to_reference().reference_id,
            vector["expected_reference_id"],
        )
        _assert_contract_fields(
            self,
            "funding_open_interest_snapshot.schema.json",
            derivatives.to_dict(),
            "funding_open_interest_snapshot.v1",
        )

    def test_multi_horizon_request_identity_matches_shared_contract_vector(self):
        vector = json.loads(
            (
                ROOT
                / "contracts"
                / "test_vectors"
                / "multi_horizon_request_v1.json"
            ).read_text(encoding="utf-8")
        )
        request = MultiHorizonRequest.from_dict(vector["request"])

        self.assertEqual(request.content_hash, vector["expected_content_hash"])
        self.assertEqual(
            request.payload_size_bytes,
            vector["expected_payload_size_bytes"],
        )
        self.assertEqual(request.request_id, vector["expected_request_id"])
        _assert_contract_fields(
            self,
            "multi_horizon_request.schema.json",
            request.to_dict(),
            "multi_horizon_request.v1",
        )

    def test_multi_horizon_analysis_contains_contract_required_fields(self):
        vector = json.loads(
            (
                ROOT
                / "contracts"
                / "test_vectors"
                / "multi_horizon_request_v1.json"
            ).read_text(encoding="utf-8")
        )
        request = MultiHorizonRequest.from_dict(vector["request"])

        analysis = MultiHorizonAnalyzer().run(request)

        _assert_contract_fields(
            self,
            "multi_horizon_analysis.schema.json",
            analysis.to_dict(),
            "multi_horizon_analysis.v1",
        )
        self.assertEqual(analysis.aggregation_status, "not_computed")
        self.assertNotIn("direction", analysis.to_dict())

    def test_multi_horizon_execution_error_matches_contract_codes(self):
        vector = json.loads(
            (
                ROOT
                / "contracts"
                / "test_vectors"
                / "multi_horizon_request_v1.json"
            ).read_text(encoding="utf-8")
        )
        request = MultiHorizonRequest.from_dict(vector["request"])
        error = MultiHorizonExecutionError(
            "planned failure",
            code="analysis_failure",
            batch_id=f"multi-horizon:{'a' * 32}",
            request=request,
            failed_horizon="1h",
        )

        _assert_contract_fields(
            self,
            "multi_horizon_execution_error.schema.json",
            error.to_dict(),
            "multi_horizon_execution_error.v1",
        )
        schema = json.loads(
            (
                ROOT
                / "contracts"
                / "json_schema"
                / "multi_horizon_execution_error.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(schema["properties"]["code"]["enum"]),
            set(get_args(MultiHorizonExecutionCode)),
        )

    def test_horizon_decision_identity_matches_shared_contract_vector(self):
        vector = json.loads(
            (
                ROOT
                / "contracts"
                / "test_vectors"
                / "horizon_decision_v1.json"
            ).read_text(encoding="utf-8")
        )

        decision_hash = stable_json_hash(vector["identity_payload"])

        self.assertEqual(
            decision_hash,
            vector["expected_decision_hash"],
        )
        self.assertEqual(
            f"horizon-decision:{decision_hash[:24]}",
            vector["expected_decision_id"],
        )

    def test_horizon_decision_contains_contract_fields_and_enum_parity(self):
        vector = json.loads(
            (
                ROOT
                / "contracts"
                / "test_vectors"
                / "multi_horizon_request_v1.json"
            ).read_text(encoding="utf-8")
        )
        analysis = MultiHorizonAnalyzer().run(
            MultiHorizonRequest.from_dict(vector["request"])
        )

        decision = HorizonDecisionCell().analyze(analysis)

        _assert_contract_fields(
            self,
            "horizon_decision.schema.json",
            decision.to_dict(),
            "horizon_decision.v1",
        )
        schema = json.loads(
            (
                ROOT
                / "contracts"
                / "json_schema"
                / "horizon_decision.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(schema["$defs"]["alignment_status"]["enum"]),
            set(get_args(HorizonAlignmentStatus)),
        )
        self.assertEqual(
            set(schema["$defs"]["conflict_type"]["enum"]),
            set(get_args(HorizonConflictType)),
        )
        self.assertEqual(
            set(
                schema["$defs"]["band_decision"]["properties"]["band"][
                    "enum"
                ]
            ),
            set(get_args(HorizonBand)),
        )

    def test_cell_input_bundle_audit_contains_contract_required_fields(self):
        request = _request()
        snapshot = InputSnapshot.from_analysis_request(request)
        bundle = CellInputBundle(
            node_id="cell:technical.trend",
            analysis_request=request,
            resolved_inputs=(
                ResolvedCellInput(
                    reference=snapshot.to_reference(),
                    snapshot=snapshot,
                ),
            ),
            required_input_kinds=("analysis_request",),
        )

        _assert_contract_fields(
            self,
            "cell_input_bundle.schema.json",
            bundle.to_audit_dict(),
            "cell_input_bundle.v1",
        )

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
        self.assertEqual(run["schema_version"], "analysis_run.v2")
        self.assertEqual(len(run["input_snapshots"]), 1)

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
        self.assertEqual(plan["schema_version"], "cell_execution_plan.v5")
        self.assertTrue(all(node["binding_id"] for node in plan["nodes"]))
        self.assertTrue(
            all("fallback_binding_ids" in node for node in plan["nodes"])
        )
        self.assertTrue(
            all(node["required_input_kinds"] for node in plan["nodes"])
        )
        self.assertTrue(plan["service_bindings"])

    def test_input_snapshot_contains_contract_required_fields(self):
        snapshot = InputSnapshot.from_analysis_request(_request())

        _assert_contract_fields(
            self,
            "input_snapshot.schema.json",
            snapshot.to_dict(),
            "input_snapshot.v1",
        )

    def test_input_snapshot_audit_contains_contract_required_fields(self):
        snapshot = InputSnapshot.from_analysis_request(_request())
        audit = snapshot.to_audit_dict()

        _assert_contract_fields(
            self,
            "input_snapshot_audit.schema.json",
            audit,
            "input_snapshot_audit.v1",
        )
        self.assertNotIn("payload", audit)

    def test_input_reference_contains_contract_required_fields(self):
        reference = InputSnapshot.from_analysis_request(_request()).to_reference()

        _assert_contract_fields(
            self,
            "input_reference.schema.json",
            reference.to_dict(),
            "input_reference.v1",
        )
        self.assertNotIn("payload", reference.to_dict())

    def test_input_resolution_record_contains_contract_required_fields(self):
        snapshot = InputSnapshot.from_analysis_request(_request())
        reference = snapshot.to_reference()
        record = InputResolutionRecord(
            node_id="cell:technical.trend",
            reference_id=reference.reference_id,
            input_kind=reference.input_kind,
            resolver="local_memory_input_resolver_v0.1",
            status="succeeded",
            cache_hit=False,
            expected_content_hash=reference.content_hash,
            actual_content_hash=snapshot.content_hash,
            expected_payload_size_bytes=reference.payload_size_bytes,
            actual_payload_size_bytes=snapshot.payload_size_bytes,
            data_version=reference.data_version,
            source=reference.source,
        )

        _assert_contract_fields(
            self,
            "input_resolution_record.schema.json",
            record.to_dict(),
            "input_resolution_record.v1",
        )

    def test_feature_snapshot_contains_contract_required_fields(self):
        snapshot = build_feature_snapshot(
            _request().candles,
            source_input_hash="a" * 64,
        )

        _assert_contract_fields(
            self,
            "feature_snapshot.schema.json",
            snapshot.to_dict(),
            "feature_snapshot.v1",
        )

    def test_cell_graph_definition_contains_contract_required_fields(self):
        schema = json.loads(
            (
                ROOT
                / "contracts"
                / "json_schema"
                / "cell_graph_definition.schema.json"
            ).read_text(encoding="utf-8")
        )

        graph = default_analysis_graph().to_dict()

        for field_name in schema["required"]:
            with self.subTest(field_name=field_name):
                self.assertIn(field_name, graph)
        self.assertEqual(graph["schema_version"], "cell_graph_definition.v1")
        self.assertTrue(graph["nodes"])
        self.assertTrue(graph["organs"])
        self.assertTrue(all(organ["organ_version"] for organ in graph["organs"]))

    def test_cell_graph_validation_contains_contract_required_fields(self):
        schema = json.loads(
            (
                ROOT
                / "contracts"
                / "json_schema"
                / "cell_graph_validation.schema.json"
            ).read_text(encoding="utf-8")
        )
        graph = default_analysis_graph()
        root = next(node for node in graph.nodes if node.node_id == graph.root_node_id)
        invalid_root = replace(root, dependencies=[*root.dependencies, "node:missing"])
        invalid = replace(
            graph,
            nodes=[
                invalid_root if node.node_id == root.node_id else node
                for node in graph.nodes
            ],
        )

        with self.assertRaises(CellGraphValidationError) as context:
            validate_cell_graph_definition(invalid)
        validation = context.exception.to_dict()

        for field_name in schema["required"]:
            with self.subTest(field_name=field_name):
                self.assertIn(field_name, validation)
        self.assertEqual(validation["schema_version"], "cell_graph_validation.v1")
        schema_codes = set(schema["$defs"]["issue"]["properties"]["code"]["enum"])
        self.assertEqual(schema_codes, set(get_args(GraphValidationCode)))

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

    def test_runtime_summary_snapshot_contains_contract_required_fields(self):
        snapshot = RuntimeSummarySnapshot.empty(window=timedelta(days=30))

        _assert_contract_fields(
            self,
            "runtime_summary_snapshot.schema.json",
            snapshot.to_dict(),
            "runtime_summary_snapshot.v1",
        )

    def test_runtime_summary_write_contains_contract_required_fields(self):
        write = RuntimeSummaryWriteRecord.disabled(7)

        _assert_contract_fields(
            self,
            "runtime_summary_write.schema.json",
            write.to_dict(),
            "runtime_summary_write.v1",
        )

    def test_performance_baseline_contains_contract_required_fields(self):
        baseline = json.loads(
            (ROOT / "benchmarks" / "default_analysis.json").read_text(
                encoding="utf-8"
            )
        )

        _assert_contract_fields(
            self,
            "performance_baseline.schema.json",
            baseline,
            "performance_baseline.v1",
        )

    def test_performance_result_contains_contract_required_fields(self):
        durations = DurationDistribution(
            sample_count=5,
            average_ms=1,
            min_ms=1,
            p50_ms=1,
            p95_ms=1,
            p99_ms=1,
            max_ms=1,
        )
        result = PerformanceBenchmarkResult(
            benchmark_id="contract-test",
            baseline_schema_version="performance_baseline.v1",
            input_hash="a" * 64,
            warmup_runs=1,
            measured_runs=5,
            expected_node_count=1,
            thresholds=PerformanceThresholds(
                total_p95_ms=100,
                node_p95_ms=10,
                rationale="contract test",
            ),
            reference_measurement=ReferenceMeasurement(
                environment="contract test",
                measured_at="2026-07-16T00:00:00+00:00",
                total_p95_ms=1,
                slowest_node_p95_ms=0.1,
            ),
            total_durations=durations,
            nodes=[
                NodePerformance(
                    node_id="cell:root.decision",
                    cell_id="root.decision",
                    durations=durations,
                )
            ],
            slowest_node_id="cell:root.decision",
            actual_decision={"direction": "neutral"},
            actual_formula_versions={"root.decision": "v1"},
            correctness_failures=[],
            performance_failures=[],
            environment={"python": "3.11"},
            created_at="2026-07-16T00:00:00+00:00",
        )

        _assert_contract_fields(
            self,
            "performance_benchmark_result.schema.json",
            result.to_dict(),
            "performance_benchmark_result.v1",
        )

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
        self.assertEqual(decision["schema_version"], "cell_placement_decision.v3")
        self.assertTrue(decision["selected_binding_id"])

    def test_execution_control_record_contains_contract_required_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(report_store=store).run(_request())
            run = store.load_run(report.run_id or "")
            record = run["metadata"]["execution_control_records"][0]

        _assert_contract_fields(
            self,
            "execution_control_record.schema.json",
            record,
            "execution_control_record.v1",
        )
        schema = json.loads(
            (
                ROOT
                / "contracts"
                / "json_schema"
                / "execution_control_record.schema.json"
            ).read_text(encoding="utf-8")
        )
        for field_name in schema["$defs"]["attempt"]["required"]:
            with self.subTest(field_name=field_name):
                self.assertIn(field_name, record["attempts"][0])

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

    def test_replay_comparison_contains_contract_required_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(report_store=store).run(_request())
            comparison = ReplayRunner(store).replay(report.report_id or "")

        _assert_contract_fields(
            self,
            "replay_comparison.schema.json",
            comparison.to_dict(),
            "replay_comparison.v1",
        )


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        target="BTC/USD",
        horizon="1h",
        candles=[
            Candle("t1", open=100, high=101, low=99, close=100, volume=1000),
            Candle("t2", open=100, high=102, low=99, close=101, volume=1200),
        ],
    )


def _assert_contract_fields(
    test_case: unittest.TestCase,
    schema_name: str,
    payload: dict,
    schema_version: str,
) -> None:
    schema = json.loads(
        (ROOT / "contracts" / "json_schema" / schema_name).read_text(
            encoding="utf-8"
        )
    )
    for field_name in schema["required"]:
        with test_case.subTest(schema=schema_name, field_name=field_name):
            test_case.assertIn(field_name, payload)
    test_case.assertEqual(payload["schema_version"], schema_version)


def _schema_references(value):
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith(
            "https://marketcell.local/schemas/"
        ):
            yield reference
        for child in value.values():
            yield from _schema_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _schema_references(child)


if __name__ == "__main__":
    unittest.main()
