from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_cell.engine import AnalysisEngine
from market_cell.events import EventBus
from market_cell.execution import (
    ExecutionPlanValidationError,
    build_local_execution_plan,
    validate_execution_plan,
)
from market_cell.models import AnalysisRequest, Candle
from market_cell.registry import default_registry
from market_cell.reports import FileSystemReportStore


class ExecutionPlanValidationTests(unittest.TestCase):
    def test_valid_plan_returns_deterministic_topological_levels(self):
        plan = build_local_execution_plan(default_registry(), _request())

        validated = validate_execution_plan(plan)

        expected_leaves = sorted(
            node.node_id for node in plan.nodes if node.execution_role == "leaf"
        )
        self.assertEqual(validated.topological_levels, [expected_leaves, [plan.root_node_id]])
        self.assertEqual(plan.metadata["topological_levels"], validated.topological_levels)

    def test_same_cell_can_appear_in_multiple_nodes(self):
        plan = _plan_with_repeated_cell()

        validated = validate_execution_plan(plan)

        repeated_cell_nodes = [
            node for node in plan.nodes if node.cell_id == "technical.trend"
        ]
        self.assertEqual(len(repeated_cell_nodes), 2)
        self.assertEqual(len({node.node_id for node in repeated_cell_nodes}), 2)
        self.assertEqual(validated.topological_levels[-1], [plan.root_node_id])

    def test_validator_rejects_duplicate_node_id(self):
        plan = build_local_execution_plan(default_registry(), _request())
        invalid = replace(plan, nodes=[*plan.nodes, plan.nodes[0]])

        error = _validation_error(invalid)

        self.assertIn("duplicate_node_id", _issue_codes(error))

    def test_validator_rejects_missing_root(self):
        plan = build_local_execution_plan(default_registry(), _request())
        invalid = replace(plan, root_node_id="cell:missing-root")

        error = _validation_error(invalid)

        self.assertIn("missing_root", _issue_codes(error))

    def test_validator_rejects_duplicate_binding_id(self):
        plan = build_local_execution_plan(default_registry(), _request())
        invalid = replace(
            plan,
            service_bindings=[*plan.service_bindings, plan.service_bindings[0]],
        )

        error = _validation_error(invalid)

        self.assertIn("duplicate_binding_id", _issue_codes(error))

    def test_validator_rejects_missing_dependency(self):
        plan = build_local_execution_plan(default_registry(), _request())
        root = _root(plan)
        invalid_root = replace(root, dependencies=[*root.dependencies, "cell:missing"])
        invalid = replace(plan, nodes=_replace_node(plan, invalid_root))

        error = _validation_error(invalid)

        self.assertIn("missing_dependency", _issue_codes(error))

    def test_validator_rejects_cycle(self):
        plan = build_local_execution_plan(default_registry(), _request())
        leaf = next(node for node in plan.nodes if node.execution_role == "leaf")
        cyclic_leaf = replace(
            leaf,
            execution_role="aggregator",
            dependencies=[plan.root_node_id],
        )
        invalid = replace(plan, nodes=_replace_node(plan, cyclic_leaf))

        error = _validation_error(invalid)

        self.assertIn("cycle_detected", _issue_codes(error))

    def test_validator_rejects_unreachable_node(self):
        plan = build_local_execution_plan(default_registry(), _request())
        root = _root(plan)
        orphan_id = root.dependencies[0]
        invalid_root = replace(
            root,
            dependencies=[node_id for node_id in root.dependencies if node_id != orphan_id],
        )
        invalid = replace(plan, nodes=_replace_node(plan, invalid_root))

        error = _validation_error(invalid)

        self.assertIn("unreachable_node", _issue_codes(error))

    def test_validator_rejects_node_binding_mismatch(self):
        plan = build_local_execution_plan(default_registry(), _request())
        first, second = plan.nodes[0], plan.nodes[1]
        invalid_node = replace(first, binding_id=second.binding_id)
        invalid = replace(plan, nodes=_replace_node(plan, invalid_node))

        error = _validation_error(invalid)

        self.assertIn("binding_cell_mismatch", _issue_codes(error))

    def test_validator_rejects_formula_mismatch(self):
        plan = build_local_execution_plan(default_registry(), _request())
        node = plan.nodes[0]
        invalid_node = replace(node, formula_version="other-formula")
        invalid = replace(plan, nodes=_replace_node(plan, invalid_node))

        error = _validation_error(invalid)

        self.assertIn("binding_formula_mismatch", _issue_codes(error))

    def test_engine_persists_invalid_plan_before_any_cell_executes(self):
        registry = default_registry()
        valid_plan = build_local_execution_plan(registry, _request())
        root = _root(valid_plan)
        invalid_root = replace(root, dependencies=[*root.dependencies, "cell:missing"])
        invalid_plan = replace(valid_plan, nodes=_replace_node(valid_plan, invalid_root))
        event_bus = EventBus()
        first_cell = registry.resolve("technical.trend")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            engine = _FixedPlanEngine(
                invalid_plan,
                registry=registry,
                event_bus=event_bus,
                report_store=store,
            )
            with patch.object(first_cell, "analyze", wraps=first_cell.analyze) as analyze:
                with self.assertRaises(ExecutionPlanValidationError):
                    engine.run(_request())
            failed_event = next(event for event in event_bus.events if event.name == "analysis.failed")
            run = store.load_run(failed_event.payload["run_id"])

        analyze.assert_not_called()
        self.assertEqual(run["status"], "failed")
        self.assertEqual(
            run["metadata"]["cell_execution_plan"]["schema_version"],
            "cell_execution_plan.v2",
        )
        self.assertEqual(run["metadata"]["cell_runtime_traces"], [])
        validation = run["metadata"]["execution_plan_validation"]
        self.assertEqual(validation["error_type"], "execution_plan_validation")
        self.assertEqual(validation["schema_version"], "execution_plan_validation.v1")
        self.assertIn(
            "missing_dependency",
            {issue["code"] for issue in validation["issues"]},
        )


class _FixedPlanEngine(AnalysisEngine):
    def __init__(self, plan, **kwargs) -> None:
        super().__init__(**kwargs)
        self.plan = plan

    def _execution_plan(self, request):
        return self.plan


def _plan_with_repeated_cell():
    plan = build_local_execution_plan(default_registry(), _request())
    trend = next(node for node in plan.nodes if node.cell_id == "technical.trend")
    root = _root(plan)
    duplicate = replace(trend, node_id="cell:technical.trend:secondary")
    reduced_root = replace(root, dependencies=[trend.node_id, duplicate.node_id])
    used_binding_ids = {trend.binding_id, root.binding_id}
    return replace(
        plan,
        nodes=[trend, duplicate, reduced_root],
        service_bindings=[
            binding
            for binding in plan.service_bindings
            if binding.binding_id in used_binding_ids
        ],
    )


def _root(plan):
    return next(node for node in plan.nodes if node.node_id == plan.root_node_id)


def _replace_node(plan, replacement):
    return [
        replacement if node.node_id == replacement.node_id else node
        for node in plan.nodes
    ]


def _validation_error(plan):
    try:
        validate_execution_plan(plan)
    except ExecutionPlanValidationError as exc:
        return exc
    raise AssertionError("expected ExecutionPlanValidationError")


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
