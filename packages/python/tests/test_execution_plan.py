import tempfile
import unittest
from pathlib import Path

from market_cell.engine import AnalysisEngine
from market_cell.execution import CellRuntimeTrace, build_local_execution_plan, summarize_runtime_traces
from market_cell.models import AnalysisRequest, Candle
from market_cell.registry import default_registry
from market_cell.reports import FileSystemReportStore


class CellExecutionPlanTests(unittest.TestCase):
    def test_local_execution_plan_maps_all_registry_cells_to_single_service(self):
        request = _request()
        registry = default_registry()

        plan = build_local_execution_plan(registry, request)

        self.assertEqual(plan.schema_version, "cell_execution_plan.v1")
        self.assertEqual(plan.target, "BTC/USD")
        self.assertEqual(plan.horizon, "1h")
        self.assertEqual(len(plan.nodes), len(registry.all_cells()))
        self.assertEqual(len(plan.service_bindings), len(registry.all_cells()))
        self.assertEqual({binding.service_id for binding in plan.service_bindings}, {"python-local"})
        self.assertEqual({binding.runtime for binding in plan.service_bindings}, {"python_local"})
        self.assertEqual({binding.task_queue for binding in plan.service_bindings}, {"cell.python-local"})

    def test_local_execution_plan_keeps_leaf_nodes_parallelizable(self):
        plan = build_local_execution_plan(default_registry(), _request())
        root = next(node for node in plan.nodes if node.node_id == plan.root_node_id)
        leaves = [node for node in plan.nodes if node.execution_role == "leaf"]

        self.assertEqual(root.execution_role, "root")
        self.assertEqual(set(root.dependencies), {node.node_id for node in leaves})
        self.assertTrue(all(not node.dependencies for node in leaves))

    def test_execution_plan_can_be_persisted_in_run_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(report_store=store).run(_request())
            run = store.load_run(report.run_id or "")

        plan = run["metadata"]["cell_execution_plan"]
        self.assertEqual(plan["schema_version"], "cell_execution_plan.v1")
        self.assertEqual(plan["root_node_id"], "cell:root.decision")

    def test_cell_runtime_traces_are_persisted_in_run_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(report_store=store).run(_request())
            run = store.load_run(report.run_id or "")

        traces = run["metadata"]["cell_runtime_traces"]
        plan = run["metadata"]["cell_execution_plan"]

        self.assertEqual(len(traces), len(default_registry().all_cells()))
        self.assertEqual({trace["trace_id"] for trace in traces}, {traces[0]["trace_id"]})
        self.assertEqual({trace["status"] for trace in traces}, {"succeeded"})
        self.assertEqual({trace["schema_version"] for trace in traces}, {"cell_runtime_trace.v1"})
        self.assertEqual({trace["service_id"] for trace in traces}, {"python-local"})
        self.assertEqual({trace["runtime"] for trace in traces}, {"python_local"})
        self.assertEqual({trace["plan_id"] for trace in traces}, {plan["plan_id"]})
        self.assertTrue(all(trace["duration_ms"] >= 0 for trace in traces))

    def test_cell_runtime_summaries_are_persisted_in_run_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(report_store=store).run(_request())
            run = store.load_run(report.run_id or "")

        summaries = run["metadata"]["cell_runtime_summaries"]

        self.assertEqual(len(summaries), len(default_registry().all_cells()))
        self.assertEqual({summary["schema_version"] for summary in summaries}, {"cell_runtime_summary.v1"})
        self.assertEqual({summary["service_id"] for summary in summaries}, {"python-local"})
        self.assertTrue(all(summary["implementation_id"].startswith("python-local:") for summary in summaries))
        self.assertTrue(all(summary["trace_count"] == 1 for summary in summaries))
        self.assertTrue(all(summary["failed_count"] == 0 for summary in summaries))

    def test_runtime_summary_groups_by_cell_formula_implementation_service_and_runtime(self):
        traces = [
            _trace("technical.trend", "v1", "impl-python-a", "python-local", "python_local", 10, "succeeded"),
            _trace("technical.trend", "v1", "impl-python-a", "python-local", "python_local", 30, "succeeded"),
            _trace("technical.trend", "v1", "impl-python-b", "python-local", "python_local", 8, "succeeded"),
            _trace("technical.trend", "v1", "impl-rust-a", "rust-hot", "rust_service", 4, "failed", error="boom"),
        ]

        summaries = summarize_runtime_traces(traces)

        self.assertEqual(
            [summary.implementation_id for summary in summaries],
            ["impl-rust-a", "impl-python-a", "impl-python-b"],
        )
        rust_summary = summaries[0]
        python_summary = summaries[1]
        self.assertEqual(rust_summary.failed_count, 1)
        self.assertEqual(rust_summary.error_count, 1)
        self.assertEqual(python_summary.trace_count, 2)
        self.assertEqual(python_summary.average_duration_ms, 20)
        self.assertEqual(python_summary.p95_duration_ms, 30)

    def test_engine_can_disable_execution_plan_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(report_store=store, include_execution_plan=False).run(_request())
            run = store.load_run(report.run_id or "")

        self.assertNotIn("cell_execution_plan", run["metadata"])
        self.assertIn("cell_runtime_traces", run["metadata"])
        self.assertEqual({trace["plan_id"] for trace in run["metadata"]["cell_runtime_traces"]}, {None})


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        target="BTC/USD",
        horizon="1h",
        candles=[
            Candle("t1", 100, 102, 99, 101, 1000),
            Candle("t2", 101, 104, 100, 103, 1200),
            Candle("t3", 103, 106, 102, 105, 1400),
            Candle("t4", 105, 108, 104, 107, 2200),
        ],
    )


def _trace(
    cell_id: str,
    formula_version: str,
    implementation_id: str,
    service_id: str,
    runtime,
    duration_ms: float,
    status,
    *,
    error: str | None = None,
) -> CellRuntimeTrace:
    return CellRuntimeTrace(
        trace_id="trace",
        span_id=f"span-{cell_id}-{service_id}-{duration_ms}",
        run_id="run",
        node_id=f"cell:{cell_id}",
        cell_id=cell_id,
        formula_version=formula_version,
        status=status,
        started_at="2026-07-10T00:00:00+00:00",
        finished_at="2026-07-10T00:00:00+00:00",
        duration_ms=duration_ms,
        implementation_id=implementation_id,
        service_id=service_id,
        runtime=runtime,
        error=error,
    )


if __name__ == "__main__":
    unittest.main()
