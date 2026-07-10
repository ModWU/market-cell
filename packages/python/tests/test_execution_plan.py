import tempfile
import unittest
from pathlib import Path

from market_cell.engine import AnalysisEngine
from market_cell.execution import build_local_execution_plan
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

    def test_engine_can_disable_execution_plan_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(report_store=store, include_execution_plan=False).run(_request())
            run = store.load_run(report.run_id or "")

        self.assertNotIn("cell_execution_plan", run["metadata"])


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


if __name__ == "__main__":
    unittest.main()
