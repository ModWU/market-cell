from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_cell.cells.base import MarketCell
from market_cell.engine import AnalysisEngine
from market_cell.events import EventBus
from market_cell.execution import build_local_execution_plan
from market_cell.graph import (
    CellGraphDefinition,
    CellGraphNode,
    CellGraphValidationError,
    CellOrganDefinition,
    default_analysis_graph,
    validate_cell_graph_definition,
)
from market_cell.models import AnalysisRequest, Candle, CellResult
from market_cell.registry import CellRegistry, default_registry
from market_cell.replay import ReplayRunner
from market_cell.reports import FileSystemReportStore


class CellGraphDefinitionTests(unittest.TestCase):
    def test_default_graph_is_versioned_and_organs_can_share_nodes(self):
        graph = default_analysis_graph()

        validated = validate_cell_graph_definition(
            graph,
            default_registry().manifests(),
        )

        self.assertEqual(graph.schema_version, "cell_graph_definition.v1")
        self.assertEqual(graph.graph_id, "market.default_analysis")
        self.assertEqual(validated.topological_levels[-1], [graph.root_node_id])
        technical = _organ(graph, "organ.technical_structure")
        risk = _organ(graph, "organ.market_risk")
        self.assertIn("cell:technical.volatility", technical.node_ids)
        self.assertIn("cell:technical.volatility", risk.node_ids)

    def test_graph_definition_contains_no_service_location(self):
        payload = default_analysis_graph().to_dict()
        serialized = str(payload)

        self.assertNotIn("binding_id", serialized)
        self.assertNotIn("implementation_id", serialized)
        self.assertNotIn("service_id", serialized)
        self.assertNotIn("runtime", serialized)

    def test_planner_builds_multilevel_plan_from_graph_not_registry_order(self):
        calls: list[str] = []
        first = _GraphCell("test.first", calls)
        second = _GraphCell("test.second", calls)
        aggregator = _GraphCell("test.aggregator", calls)
        root = _GraphCell("test.root", calls)
        registry = CellRegistry([root, second, aggregator, first])
        graph = _multilevel_graph(first, second, aggregator, root)

        plan = build_local_execution_plan(
            registry,
            _request(),
            graph_definition=graph,
        )

        self.assertEqual(plan.root_node_id, "node:root")
        self.assertEqual(plan.metadata["graph_id"], graph.graph_id)
        self.assertEqual(plan.metadata["graph_version"], graph.graph_version)
        self.assertEqual(
            plan.metadata["topological_levels"],
            [["node:first", "node:second"], ["node:aggregator"], ["node:root"]],
        )
        self.assertEqual(plan.metadata["node_count"], 4)
        self.assertEqual(plan.metadata["organ_count"], 2)
        self.assertEqual(
            plan.metadata["organs"],
            [
                {"organ_id": "organ.signals", "organ_version": "1.0.0"},
                {"organ_id": "organ.shared_first", "organ_version": "1.0.0"},
            ],
        )

    def test_engine_executes_multilevel_graph_and_persists_graph_audit(self):
        calls: list[str] = []
        first = _GraphCell("test.first", calls)
        second = _GraphCell("test.second", calls)
        aggregator = _GraphCell("test.aggregator", calls)
        root = _GraphCell("test.root", calls)
        registry = CellRegistry([root, second, aggregator, first])
        graph = _multilevel_graph(first, second, aggregator, root)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(
                registry=registry,
                graph_definition=graph,
                report_store=store,
            ).run(_request())
            run = store.load_run(report.run_id or "")

        self.assertEqual(
            calls,
            ["test.first", "test.second", "test.aggregator", "test.root"],
        )
        self.assertEqual(report.decision.cell_id, "test.root")
        self.assertEqual(report.decision.children[0].cell_id, "test.aggregator")
        self.assertEqual(
            report.decision.children[0].metadata["child_ids"],
            ["test.second", "test.first"],
        )
        self.assertEqual(
            run["metadata"]["cell_graph_definition"]["graph_id"],
            graph.graph_id,
        )
        self.assertEqual(
            run["metadata"]["plan_execution"]["execution_order"],
            ["node:first", "node:second", "node:aggregator", "node:root"],
        )

    def test_repeated_cell_nodes_share_placement_but_execute_independently(self):
        graph = CellGraphDefinition(
            graph_id="test.repeated_cell",
            graph_version="1.0.0",
            name="Repeated Cell",
            root_node_id="node:root",
            nodes=[
                CellGraphNode(
                    "node:root",
                    "root.decision",
                    "root",
                    ["node:trend:secondary", "node:trend:primary"],
                ),
                CellGraphNode("node:trend:secondary", "technical.trend", "leaf"),
                CellGraphNode("node:trend:primary", "technical.trend", "leaf"),
            ],
        )
        registry = default_registry()

        plan = build_local_execution_plan(
            registry,
            _request(),
            graph_definition=graph,
        )
        report = AnalysisEngine(
            registry=registry,
            graph_definition=graph,
        ).run(_request())

        trend_nodes = [node for node in plan.nodes if node.cell_id == "technical.trend"]
        self.assertEqual(len(trend_nodes), 2)
        self.assertEqual(len({node.binding_id for node in trend_nodes}), 1)
        self.assertEqual(len(plan.service_bindings), 2)
        self.assertEqual(len(plan.metadata["placement_decisions"]), 2)
        self.assertEqual(
            [child.cell_id for child in report.decision.children],
            ["technical.trend", "technical.trend"],
        )
        self.assertEqual(
            set(report.formula_versions),
            {"technical.trend", "root.decision"},
        )

    def test_multilevel_graph_replays_with_stable_graph_and_result(self):
        calls: list[str] = []
        first = _GraphCell("test.first", calls)
        second = _GraphCell("test.second", calls)
        aggregator = _GraphCell("test.aggregator", calls)
        root = _GraphCell("test.root", calls)
        registry = CellRegistry([root, second, aggregator, first])
        graph = _multilevel_graph(first, second, aggregator, root)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(
                registry=registry,
                graph_definition=graph,
                report_store=store,
            ).run(_request())
            comparison = ReplayRunner(
                store,
                engine_factory=lambda: AnalysisEngine(
                    registry=registry,
                    graph_definition=graph,
                ),
            ).replay(report.report_id or "")

        self.assertTrue(comparison.result_stable)
        self.assertEqual(comparison.formula_version_changes, {})
        self.assertEqual(comparison.graph_definition_changes, {})

    def test_validator_rejects_organ_dependency_outside_named_subgraph(self):
        calls: list[str] = []
        first = _GraphCell("test.first", calls)
        second = _GraphCell("test.second", calls)
        aggregator = _GraphCell("test.aggregator", calls)
        root = _GraphCell("test.root", calls)
        graph = _multilevel_graph(first, second, aggregator, root)
        invalid_organ = replace(
            graph.organs[0],
            node_ids=["node:aggregator"],
        )
        invalid = replace(graph, organs=[invalid_organ, *graph.organs[1:]])

        error = _graph_validation_error(invalid)

        self.assertIn("organ_dependency_outside_subgraph", _issue_codes(error))

    def test_validator_rejects_cycles(self):
        graph = CellGraphDefinition(
            graph_id="test.cycle",
            graph_version="1.0.0",
            name="Cycle",
            root_node_id="node:root",
            nodes=[
                CellGraphNode("node:a", "test.a", "aggregator", ["node:root"]),
                CellGraphNode("node:root", "test.root", "root", ["node:a"]),
            ],
        )

        error = _graph_validation_error(graph)

        self.assertIn("cycle_detected", _issue_codes(error))

    def test_engine_persists_invalid_graph_before_any_cell_executes(self):
        registry = default_registry()
        graph = default_analysis_graph()
        first = graph.nodes[0]
        invalid = replace(
            graph,
            nodes=[
                replace(first, cell_id="missing.cell"),
                *graph.nodes[1:],
            ],
        )
        event_bus = EventBus()
        observed_cell = registry.resolve("technical.volume")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            with patch.object(
                observed_cell,
                "analyze",
                wraps=observed_cell.analyze,
            ) as analyze:
                with self.assertRaises(CellGraphValidationError):
                    AnalysisEngine(
                        registry=registry,
                        graph_definition=invalid,
                        event_bus=event_bus,
                        report_store=store,
                    ).run(_request())
            failed_event = next(
                event for event in event_bus.events if event.name == "analysis.failed"
            )
            run = store.load_run(failed_event.payload["run_id"])

        analyze.assert_not_called()
        self.assertEqual(run["status"], "failed")
        self.assertNotIn("cell_execution_plan", run["metadata"])
        self.assertEqual(run["metadata"]["cell_runtime_traces"], [])
        validation = run["metadata"]["cell_graph_validation"]
        self.assertEqual(validation["error_type"], "cell_graph_validation")
        self.assertEqual(validation["schema_version"], "cell_graph_validation.v1")
        self.assertIn(
            "missing_cell_implementation",
            {issue["code"] for issue in validation["issues"]},
        )


class _GraphCell(MarketCell):
    def __init__(self, cell_id: str, calls: list[str]) -> None:
        self.cell_id = cell_id
        self.name = cell_id
        self.category = "test"
        self.formula_version = "test.v1"
        self.inputs = []
        self.outputs = ["result"]
        self.calls = calls

    def analyze(
        self,
        request: AnalysisRequest,
        child_results: list[CellResult] | None = None,
    ) -> CellResult:
        children = list(child_results or [])
        self.calls.append(self.cell_id)
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
            score=0,
            explanation=self.cell_id,
            children=children,
            metadata={"child_ids": [child.cell_id for child in children]},
        )


def _multilevel_graph(first, second, aggregator, root):
    return CellGraphDefinition(
        graph_id="test.multilevel",
        graph_version="1.0.0",
        name="Multilevel Graph",
        root_node_id="node:root",
        nodes=[
            CellGraphNode("node:root", root.cell_id, "root", ["node:aggregator"]),
            CellGraphNode(
                "node:aggregator",
                aggregator.cell_id,
                "aggregator",
                ["node:second", "node:first"],
            ),
            CellGraphNode("node:second", second.cell_id, "leaf"),
            CellGraphNode("node:first", first.cell_id, "leaf"),
        ],
        organs=[
            CellOrganDefinition(
                organ_id="organ.signals",
                organ_version="1.0.0",
                name="Signals",
                node_ids=["node:first", "node:second", "node:aggregator"],
                output_node_ids=["node:aggregator"],
            ),
            CellOrganDefinition(
                organ_id="organ.shared_first",
                organ_version="1.0.0",
                name="Shared First",
                node_ids=["node:first"],
                output_node_ids=["node:first"],
            ),
        ],
    )


def _organ(graph, organ_id):
    return next(organ for organ in graph.organs if organ.organ_id == organ_id)


def _graph_validation_error(graph):
    try:
        validate_cell_graph_definition(graph)
    except CellGraphValidationError as exc:
        return exc
    raise AssertionError("expected CellGraphValidationError")


def _issue_codes(error):
    return {issue.code for issue in error.issues}


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
