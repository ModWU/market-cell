from dataclasses import replace
import unittest

from market_cell.cells.base import MarketCell
from market_cell.engine import AnalysisEngine
from market_cell.events import EventBus
from market_cell.execution import (
    CellExecutionNode,
    CellExecutionPlan,
    LocalCellExecutor,
    PlanDrivenLocalCoordinator,
    build_local_service_binding,
    validate_execution_plan,
)
from market_cell.models import AnalysisRequest, Candle, CellResult
from market_cell.inputs import InputSnapshot, LocalInputResolver
from market_cell.registry import CellNotRegisteredError, CellRegistry


class PlanDrivenLocalCoordinatorTests(unittest.TestCase):
    def test_plan_topology_controls_execution_and_dependency_result_order(self):
        calls: list[str] = []
        first = _RecordingCell("test.first", calls)
        second = _RecordingCell("test.second", calls)
        root = _RecordingCell("test.root", calls)
        registry = CellRegistry([second, first, root])
        nodes = [
            _node("node:root", root, "root", ["node:second", "node:first"]),
            _node("node:second", second, "leaf"),
            _node("node:first", first, "leaf"),
        ]
        plan = _plan(nodes, "node:root", [root, second, first])
        executor = _ContextRecordingExecutor()

        outcome = _execute(plan, registry, executor=executor)

        self.assertEqual(
            outcome.execution_order,
            ["node:first", "node:second", "node:root"],
        )
        self.assertEqual(calls, ["test.first", "test.second", "test.root"])
        self.assertEqual(
            root.received_child_ids,
            [["test.second", "test.first"]],
        )
        self.assertIs(outcome.root_result, outcome.results_by_node_id["node:root"])
        self.assertIs(outcome.unwrap(), outcome.root_result)
        self.assertEqual(
            [context.node.node_id for context in executor.contexts],
            outcome.execution_order,
        )
        self.assertTrue(
            all(
                context.node.binding_id == context.binding.binding_id
                for context in executor.contexts
            )
        )

    def test_multi_level_aggregator_graph_executes_level_by_level(self):
        calls: list[str] = []
        first = _RecordingCell("test.first", calls)
        second = _RecordingCell("test.second", calls)
        aggregator = _RecordingCell("test.aggregator", calls)
        root = _RecordingCell("test.root", calls)
        registry = CellRegistry([aggregator, second, first, root])
        nodes = [
            _node("node:root", root, "root", ["node:aggregator"]),
            _node(
                "node:aggregator",
                aggregator,
                "aggregator",
                ["node:second", "node:first"],
            ),
            _node("node:second", second, "leaf"),
            _node("node:first", first, "leaf"),
        ]
        plan = _plan(nodes, "node:root", [root, aggregator, second, first])

        outcome = _execute(plan, registry)

        self.assertEqual(
            outcome.execution_order,
            ["node:first", "node:second", "node:aggregator", "node:root"],
        )
        self.assertEqual(
            aggregator.received_child_ids,
            [["test.second", "test.first"]],
        )
        self.assertEqual(root.received_child_ids, [["test.aggregator"]])

    def test_repeated_cell_id_executes_independently_by_node_id(self):
        calls: list[str] = []
        shared = _RecordingCell("test.shared", calls)
        root = _RecordingCell("test.root", calls)
        registry = CellRegistry([shared, root])
        nodes = [
            _node(
                "node:root",
                root,
                "root",
                ["node:shared:secondary", "node:shared:primary"],
            ),
            _node("node:shared:secondary", shared, "leaf"),
            _node("node:shared:primary", shared, "leaf"),
        ]
        plan = _plan(nodes, "node:root", [root, shared])

        outcome = _execute(plan, registry)

        self.assertEqual(shared.call_count, 2)
        self.assertEqual(
            outcome.execution_order,
            ["node:shared:primary", "node:shared:secondary", "node:root"],
        )
        self.assertEqual(
            outcome.results_by_node_id["node:shared:primary"].metadata["call"],
            1,
        )
        self.assertEqual(
            outcome.results_by_node_id["node:shared:secondary"].metadata["call"],
            2,
        )
        self.assertEqual(root.received_child_calls, [[2, 1]])
        self.assertEqual(
            [trace.node_id for trace in outcome.runtime_traces],
            outcome.execution_order,
        )

    def test_missing_registry_implementation_returns_structured_failure(self):
        calls: list[str] = []
        missing = _RecordingCell("test.missing", calls)
        root = _RecordingCell("test.root", calls)
        registry = CellRegistry([root])
        nodes = [
            _node("node:root", root, "root", ["node:missing"]),
            _node("node:missing", missing, "leaf"),
        ]
        plan = _plan(nodes, "node:root", [root, missing])

        outcome = _execute(plan, registry)

        self.assertFalse(outcome.succeeded)
        self.assertEqual(outcome.failed_node_id, "node:missing")
        self.assertIsInstance(outcome.error, CellNotRegisteredError)
        self.assertEqual(outcome.execution_order, ["node:missing"])
        self.assertEqual(outcome.results_by_node_id, {})
        self.assertEqual(outcome.runtime_traces, [])
        with self.assertRaises(CellNotRegisteredError):
            outcome.unwrap()

    def test_failure_keeps_partial_results_traces_and_execution_order(self):
        calls: list[str] = []
        first = _RecordingCell("test.first", calls)
        second = _RecordingCell("test.second", calls, failure="planned failure")
        root = _RecordingCell("test.root", calls)
        registry = CellRegistry([second, first, root])
        nodes = [
            _node("node:root", root, "root", ["node:first", "node:second"]),
            _node("node:second", second, "leaf"),
            _node("node:first", first, "leaf"),
        ]
        plan = _plan(nodes, "node:root", [root, second, first])
        completions = []

        outcome = _execute(plan, registry, on_node_completed=completions.append)

        self.assertEqual(outcome.execution_order, ["node:first", "node:second"])
        self.assertEqual(list(outcome.results_by_node_id), ["node:first"])
        self.assertEqual(
            [trace.status for trace in outcome.runtime_traces],
            ["succeeded", "failed"],
        )
        self.assertEqual(outcome.failed_node_id, "node:second")
        self.assertEqual([item.node_id for item in completions], outcome.execution_order)
        self.assertIsNone(completions[-1].result)
        self.assertEqual(completions[-1].binding_id, nodes[1].binding_id)

    def test_engine_delegates_to_coordinator_and_events_include_node_identity(self):
        event_bus = EventBus()
        coordinator = _RecordingCoordinator()

        report = AnalysisEngine(
            event_bus=event_bus,
            coordinator=coordinator,
        ).run(_request())

        self.assertEqual(report.decision.cell_id, "root.decision")
        self.assertEqual(coordinator.call_count, 1)
        completed = [event for event in event_bus.events if event.name == "cell.completed"]
        self.assertTrue(completed)
        self.assertTrue(all(event.payload["node_id"] for event in completed))
        self.assertTrue(all(event.payload["binding_id"] for event in completed))
        self.assertTrue(
            all(event.payload["input_reference_ids"] for event in completed)
        )
        self.assertEqual(
            {event.payload["execution_role"] for event in completed},
            {"leaf", "aggregator", "root"},
        )


class _RecordingCell(MarketCell):
    def __init__(
        self,
        cell_id: str,
        calls: list[str],
        failure: str | None = None,
    ) -> None:
        self.cell_id = cell_id
        self.name = cell_id
        self.category = "test"
        self.formula_version = "test.v1"
        self.inputs = []
        self.outputs = ["result"]
        self.calls = calls
        self.failure = failure
        self.call_count = 0
        self.received_child_ids: list[list[str]] = []
        self.received_child_calls: list[list[int]] = []

    def analyze(
        self,
        request: AnalysisRequest,
        child_results: list[CellResult] | None = None,
    ) -> CellResult:
        self.call_count += 1
        self.calls.append(self.cell_id)
        children = list(child_results or [])
        self.received_child_ids.append([result.cell_id for result in children])
        self.received_child_calls.append(
            [int(result.metadata["call"]) for result in children]
        )
        if self.failure is not None:
            raise RuntimeError(self.failure)
        return CellResult(
            cell_id=self.cell_id,
            name=self.name,
            category=self.category,
            target=request.target,
            horizon=request.horizon,
            direction="neutral",
            strength=0,
            confidence=50,
            volatility_risk=0,
            manipulation_risk=0,
            urgency=0,
            score=float(self.call_count),
            explanation=self.cell_id,
            children=children,
            metadata={"call": self.call_count},
        )


class _RecordingCoordinator:
    def __init__(self) -> None:
        self.delegate = PlanDrivenLocalCoordinator()
        self.call_count = 0

    @property
    def name(self) -> str:
        return "recording_coordinator"

    def execute(self, **kwargs):
        self.call_count += 1
        return self.delegate.execute(**kwargs)


class _ContextRecordingExecutor:
    def __init__(self) -> None:
        self.delegate = LocalCellExecutor()
        self.contexts = []

    @property
    def name(self) -> str:
        return "context_recording_executor"

    def execute(self, **kwargs):
        self.contexts.append(kwargs["context"])
        return self.delegate.execute(**kwargs)


def _node(node_id, cell, execution_role, dependencies=None):
    binding = build_local_service_binding(cell.manifest(), "python-local")
    return CellExecutionNode(
        node_id=node_id,
        cell_id=cell.cell_id,
        formula_version=cell.formula_version,
        execution_role=execution_role,
        binding_id=binding.binding_id,
        dependencies=list(dependencies or []),
    )


def _plan(nodes, root_node_id, cells):
    reference = _input_snapshot().to_reference()
    bindings = []
    seen_binding_ids = set()
    for cell in cells:
        binding = build_local_service_binding(cell.manifest(), "python-local")
        if binding.binding_id not in seen_binding_ids:
            bindings.append(binding)
            seen_binding_ids.add(binding.binding_id)
    return CellExecutionPlan(
        plan_id="test-plan",
        target="BTC/USD",
        horizon="1h",
        root_node_id=root_node_id,
        nodes=[
            replace(node, input_reference_ids=[reference.reference_id])
            for node in nodes
        ],
        input_references=[reference],
        service_bindings=bindings,
    )


def _execute(plan, registry, on_node_completed=None, executor=None):
    input_resolver = LocalInputResolver()
    input_resolver.register(_input_snapshot())
    return PlanDrivenLocalCoordinator().execute(
        validated_plan=validate_execution_plan(plan),
        registry=registry,
        executor=executor or LocalCellExecutor(),
        input_resolver=input_resolver,
        run_id="test-run",
        trace_id="test-trace",
        on_node_completed=on_node_completed,
    )


def _input_snapshot():
    return InputSnapshot.from_analysis_request(_request())


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        target="BTC/USD",
        horizon="1h",
        candles=[
            Candle("t1", 100, 102, 99, 101, 1000),
            Candle("t2", 101, 104, 100, 103, 1200),
        ],
    )


if __name__ == "__main__":
    unittest.main()
