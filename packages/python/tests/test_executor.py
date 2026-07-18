from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_cell.engine import AnalysisEngine
from market_cell.events import EventBus
from market_cell.execution import (
    CellExecutionBindingError,
    CellExecutionContext,
    CellResultContractError,
    ExecutionTraceMismatchError,
    LocalCellExecutor,
    build_local_execution_plan,
    validate_execution_trace,
)
from market_cell.inputs import CellInputBundle, InputSnapshot, ResolvedCellInput
from market_cell.models import AnalysisRequest, Candle
from market_cell.registry import default_registry
from market_cell.graph import default_analysis_graph
from market_cell.reports import FileSystemReportStore


class LocalCellExecutorTests(unittest.TestCase):
    def test_local_executor_runs_cell_and_emits_trace_matching_plan(self):
        registry = default_registry()
        request = _request()
        plan = build_local_execution_plan(registry, request)
        cell = registry.resolve("technical.trend")

        outcome = LocalCellExecutor().execute(
            cell=cell,
            request=request,
            context=_context(plan, cell.cell_id),
        )

        self.assertEqual(outcome.unwrap().cell_id, cell.cell_id)
        self.assertEqual(outcome.trace.status, "succeeded")
        self.assertEqual(outcome.trace.service_id, "python-local")
        self.assertEqual(outcome.trace.runtime, "python_local")
        self.assertEqual(outcome.trace.metadata["executor"], "local_python_executor_v0.1")
        validate_execution_trace(outcome.trace, plan)

    def test_local_executor_without_plan_still_reports_actual_service(self):
        cell = default_registry().resolve("technical.trend")

        outcome = LocalCellExecutor().execute(
            cell=cell,
            request=_request(),
            context=CellExecutionContext(run_id="run", trace_id="trace"),
        )

        self.assertIsNone(outcome.trace.plan_id)
        self.assertEqual(outcome.trace.service_id, "python-local")
        self.assertEqual(outcome.trace.runtime, "python_local")
        self.assertFalse(outcome.trace.metadata["planned_binding"])
        validate_execution_trace(outcome.trace, None)

    def test_local_executor_rejects_remote_binding_before_cell_runs(self):
        registry = default_registry()
        request = _request()
        plan = build_local_execution_plan(registry, request)
        cell = registry.resolve("technical.trend")
        context = _context(plan, cell.cell_id)
        remote_binding = replace(
            context.binding,
            implementation_id=f"rust-hot:{cell.cell_id}:{cell.formula_version}",
            service_id="rust-hot",
            runtime="rust_service",
            language="rust",
            task_queue="cell.rust-hot",
        )
        remote_node = replace(
            context.node,
            binding_id=remote_binding.binding_id,
        )

        with patch.object(cell, "analyze", wraps=cell.analyze) as analyze:
            outcome = LocalCellExecutor().execute(
                cell=cell,
                request=request,
                context=replace(context, node=remote_node, binding=remote_binding),
            )

        analyze.assert_not_called()
        self.assertIsInstance(outcome.error, CellExecutionBindingError)
        self.assertEqual(outcome.trace.status, "failed")
        self.assertEqual(outcome.trace.service_id, "python-local")
        self.assertEqual(outcome.trace.metadata["planned_service_id"], "rust-hot")
        with self.assertRaises(CellExecutionBindingError):
            outcome.unwrap()

    def test_local_executor_rejects_incompatible_cell_result(self):
        registry = default_registry()
        request = _request()
        cell = registry.resolve("technical.trend")
        valid_result = cell.analyze(request)

        with patch.object(
            cell,
            "analyze",
            return_value=replace(valid_result, cell_id="wrong.cell"),
        ):
            outcome = LocalCellExecutor().execute(
                cell=cell,
                request=request,
                context=CellExecutionContext(run_id="run", trace_id="trace"),
            )

        self.assertIsInstance(outcome.error, CellResultContractError)
        self.assertEqual(outcome.trace.status, "failed")
        self.assertIn("cell_id", outcome.trace.error or "")

    def test_local_executor_rejects_input_bundle_reference_drift(self):
        registry = default_registry()
        request = _request()
        plan = build_local_execution_plan(registry, request)
        cell = registry.resolve("technical.trend")
        context = _context(plan, cell.cell_id)
        drifted_node = replace(
            context.node,
            input_reference_ids=["input:analysis_request:drifted"],
        )

        outcome = LocalCellExecutor().execute(
            cell=cell,
            request=request,
            context=replace(context, node=drifted_node),
        )

        self.assertIsInstance(outcome.error, CellExecutionBindingError)
        self.assertIn("input_bundle_reference_ids", outcome.trace.error or "")

    def test_trace_validator_rejects_executor_service_drift(self):
        registry = default_registry()
        request = _request()
        plan = build_local_execution_plan(registry, request)
        cell = registry.resolve("technical.trend")
        outcome = LocalCellExecutor().execute(
            cell=cell,
            request=request,
            context=_context(plan, cell.cell_id),
        )
        drifted_trace = replace(outcome.trace, service_id="unexpected-service")

        with self.assertRaises(ExecutionTraceMismatchError):
            validate_execution_trace(drifted_trace, plan)

    def test_analysis_engine_delegates_all_cells_to_injected_executor(self):
        executor = _RecordingExecutor()

        report = AnalysisEngine(executor=executor).run(_request())

        self.assertEqual(report.decision.cell_id, "root.decision")
        self.assertEqual(len(executor.contexts), len(default_analysis_graph().nodes))
        self.assertTrue(all(context.plan_id for context in executor.contexts))

    def test_analysis_engine_aligns_plan_with_custom_local_service_id(self):
        executor = LocalCellExecutor(service_id="python-research")

        report = AnalysisEngine(executor=executor).run(_request())

        self.assertEqual(report.decision.cell_id, "root.decision")

    def test_analysis_engine_persists_failed_run_with_failure_trace(self):
        registry = default_registry()
        event_bus = EventBus()
        failing_cell = registry.resolve("technical.trend")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            with patch.object(failing_cell, "analyze", side_effect=RuntimeError("cell failed")):
                with self.assertRaisesRegex(RuntimeError, "cell failed"):
                    AnalysisEngine(
                        registry=registry,
                        event_bus=event_bus,
                        report_store=store,
                    ).run(_request())
            failed_event = next(event for event in event_bus.events if event.name == "analysis.failed")
            run = store.load_run(failed_event.payload["run_id"])

        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["error"], "cell failed")
        self.assertEqual(run["metadata"]["cell_runtime_traces"][-1]["status"], "failed")
        self.assertEqual(run["metadata"]["cell_runtime_summaries"][0]["failed_count"], 1)
        plan_execution = run["metadata"]["plan_execution"]
        self.assertEqual(plan_execution["status"], "failed")
        self.assertEqual(plan_execution["failed_node_id"], f"cell:{failing_cell.cell_id}")
        self.assertEqual(
            plan_execution["execution_order"][-1],
            f"cell:{failing_cell.cell_id}",
        )
        self.assertEqual(
            plan_execution["completed_node_ids"],
            plan_execution["execution_order"][:-1],
        )
        self.assertEqual(failed_event.payload["failed_node_id"], f"cell:{failing_cell.cell_id}")
        self.assertIsNone(failed_event.payload["persistence_error"])


class _RecordingExecutor:
    def __init__(self) -> None:
        self.delegate = LocalCellExecutor()
        self.contexts: list[CellExecutionContext] = []

    @property
    def name(self) -> str:
        return "recording_executor"

    def execute(self, **kwargs):
        self.contexts.append(kwargs["context"])
        return self.delegate.execute(**kwargs)


def _context(plan, cell_id: str) -> CellExecutionContext:
    node = next(node for node in plan.nodes if node.cell_id == cell_id)
    request = _request()
    snapshot = InputSnapshot.from_analysis_request(request)
    reference = next(
        reference
        for reference in plan.input_references
        if reference.input_kind == "analysis_request"
    )
    return CellExecutionContext(
        run_id="run",
        trace_id="trace",
        plan_id=plan.plan_id,
        node=node,
        binding=next(binding for binding in plan.service_bindings if binding.binding_id == node.binding_id),
        input_bundle=CellInputBundle(
            node_id=node.node_id,
            analysis_request=request,
            resolved_inputs=(
                ResolvedCellInput(reference=reference, snapshot=snapshot),
            ),
            required_input_kinds=tuple(node.required_input_kinds),
        ),
    )


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
