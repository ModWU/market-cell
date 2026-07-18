from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from market_cell.cells.base import MarketCell
from market_cell.data import (
    DataProvenance,
    OrderBookLevel,
    OrderBookSnapshot,
)
from market_cell.engine import AnalysisEngine
from market_cell.execution import (
    ExecutionPlanValidationError,
    build_local_execution_plan,
    validate_execution_plan,
)
from market_cell.graph import CellGraphDefinition, CellGraphNode
from market_cell.inputs import (
    CellInputBundle,
    InputCompositionError,
    InputIntegrityError,
    InputSnapshot,
    LocalInputResolver,
    ResolvedCellInput,
)
from market_cell.models import AnalysisRequest, Candle, CellResult
from market_cell.registry import CellRegistry
from market_cell.replay import ReplayRunner
from market_cell.reports import FileSystemReportStore


class OrderBookSnapshotTests(unittest.TestCase):
    def test_order_book_round_trips_through_a_versioned_input_snapshot(self):
        order_book = _order_book()

        snapshot = order_book.to_input_snapshot(horizon="1h")
        restored = OrderBookSnapshot.from_input_snapshot(snapshot)

        self.assertEqual(snapshot.input_kind, "order_book_snapshot")
        self.assertEqual(snapshot.data_version, "order_book_snapshot.v1")
        self.assertEqual(snapshot.source, "binance.websocket")
        self.assertEqual(restored, order_book)
        self.assertEqual(order_book.best_bid, 100.0)
        self.assertEqual(order_book.best_ask, 100.5)
        self.assertAlmostEqual(order_book.spread_bps, 49.87531172069826)

    def test_order_book_rejects_invalid_market_structure(self):
        with self.assertRaisesRegex(ValueError, "sorted descending"):
            replace(
                _order_book(),
                bids=[
                    OrderBookLevel(99.5, 2.0),
                    OrderBookLevel(100.0, 1.0),
                ],
            )
        with self.assertRaisesRegex(ValueError, "unique"):
            replace(
                _order_book(),
                asks=[
                    OrderBookLevel(100.5, 1.0),
                    OrderBookLevel(100.5, 2.0),
                ],
            )
        with self.assertRaisesRegex(ValueError, "positive spread"):
            replace(
                _order_book(),
                asks=[OrderBookLevel(100.0, 1.0)],
            )
        with self.assertRaisesRegex(ValueError, "price must be positive"):
            OrderBookLevel(float("nan"), 1.0)
        with self.assertRaisesRegex(ValueError, "market_type"):
            replace(_order_book().provenance, market_type="invalid")

    def test_order_book_envelope_and_identity_tampering_are_rejected(self):
        snapshot = _order_book().to_input_snapshot(horizon="1h")
        resolver = LocalInputResolver()
        reference = resolver.register(snapshot)

        with self.assertRaisesRegex(InputIntegrityError, "target"):
            resolver.resolve(replace(reference, target="ETH/USD"))
        with self.assertRaisesRegex(InputIntegrityError, "horizon"):
            resolver.resolve(replace(reference, horizon="4h"))
        with self.assertRaisesRegex(InputIntegrityError, "snapshot_id"):
            LocalInputResolver().register(
                replace(snapshot, snapshot_id="snapshot:order_book_snapshot:tampered")
            )

        tampered_payload = deepcopy(snapshot.payload)
        tampered_payload["target"] = "ETH/USD"
        rehashed_tamper = InputSnapshot.create(
            input_kind="order_book_snapshot",
            target="BTC/USD",
            horizon="1h",
            payload=tampered_payload,
            data_version=snapshot.data_version,
            source=snapshot.source,
        )
        with self.assertRaisesRegex(InputIntegrityError, "target"):
            LocalInputResolver().register(rehashed_tamper)


class TypedInputCompositionTests(unittest.TestCase):
    def test_planner_binds_only_each_cells_declared_input_kinds(self):
        registry, graph, request_probe, order_book_probe = _probe_system()
        request = _request()
        request_snapshot = InputSnapshot.from_analysis_request(request)
        order_book_snapshot = _order_book().to_input_snapshot(horizon=request.horizon)

        plan = build_local_execution_plan(
            registry,
            request,
            graph_definition=graph,
            input_references=[
                request_snapshot.to_reference(),
                order_book_snapshot.to_reference(),
            ],
        )

        request_node = next(
            node for node in plan.nodes if node.cell_id == request_probe.cell_id
        )
        order_book_node = next(
            node for node in plan.nodes if node.cell_id == order_book_probe.cell_id
        )
        references = {
            reference.reference_id: reference for reference in plan.input_references
        }
        self.assertEqual(request_node.required_input_kinds, ["analysis_request"])
        self.assertEqual(
            [references[item].input_kind for item in request_node.input_reference_ids],
            ["analysis_request"],
        )
        self.assertEqual(
            order_book_node.required_input_kinds,
            ["analysis_request", "order_book_snapshot"],
        )
        self.assertEqual(
            [
                references[item].input_kind
                for item in order_book_node.input_reference_ids
            ],
            ["analysis_request", "order_book_snapshot"],
        )

    def test_missing_or_ambiguous_required_inputs_fail_during_planning(self):
        registry, graph, request_probe, order_book_probe = _probe_system()
        request = _request()
        request_reference = InputSnapshot.from_analysis_request(request).to_reference()

        with self.assertRaisesRegex(
            InputCompositionError,
            "missing required input kinds: order_book_snapshot",
        ):
            build_local_execution_plan(
                registry,
                request,
                graph_definition=graph,
                input_references=[request_reference],
            )

        second_order_book = replace(
            _order_book(),
            provenance=replace(
                _order_book().provenance,
                source_provider="coinbase.websocket",
                venue="coinbase",
            ),
        ).to_input_snapshot(horizon=request.horizon)
        with self.assertRaisesRegex(
            InputCompositionError,
            "multiple snapshots for input kinds: order_book_snapshot",
        ):
            build_local_execution_plan(
                registry,
                request,
                graph_definition=graph,
                input_references=[
                    request_reference,
                    _order_book().to_input_snapshot(
                        horizon=request.horizon
                    ).to_reference(),
                    second_order_book.to_reference(),
                ],
            )

        self.assertEqual(request_probe.received_bundles, [])
        self.assertEqual(order_book_probe.received_bundles, [])

    def test_validator_rejects_declared_and_referenced_input_kind_drift(self):
        registry, graph, _, _ = _probe_system()
        request = _request()
        request_snapshot = InputSnapshot.from_analysis_request(request)
        order_book_snapshot = _order_book().to_input_snapshot(horizon=request.horizon)
        plan = build_local_execution_plan(
            registry,
            request,
            graph_definition=graph,
            input_references=[
                request_snapshot.to_reference(),
                order_book_snapshot.to_reference(),
            ],
        )
        request_node = next(
            node for node in plan.nodes if node.cell_id == "test.request_probe"
        )
        order_book_reference = next(
            reference
            for reference in plan.input_references
            if reference.input_kind == "order_book_snapshot"
        )

        duplicate_required = replace(
            request_node,
            required_input_kinds=["analysis_request", "analysis_request"],
        )
        self.assertIn(
            "duplicate_required_input_kind",
            _validation_codes(replace(plan, nodes=_replace_node(plan, duplicate_required))),
        )

        missing_required = replace(
            request_node,
            required_input_kinds=["analysis_request", "order_book_snapshot"],
        )
        self.assertIn(
            "missing_required_input_kind",
            _validation_codes(replace(plan, nodes=_replace_node(plan, missing_required))),
        )

        unexpected = replace(
            request_node,
            input_reference_ids=[
                *request_node.input_reference_ids,
                order_book_reference.reference_id,
            ],
        )
        self.assertIn(
            "unexpected_input_kind",
            _validation_codes(replace(plan, nodes=_replace_node(plan, unexpected))),
        )

        order_book_node = next(
            node for node in plan.nodes if node.cell_id == "test.order_book_probe"
        )
        wrong_order = replace(
            order_book_node,
            input_reference_ids=list(reversed(order_book_node.input_reference_ids)),
        )
        self.assertIn(
            "unexpected_input_kind",
            _validation_codes(replace(plan, nodes=_replace_node(plan, wrong_order))),
        )

    def test_engine_composes_executes_and_audits_multi_input_bundles(self):
        registry, graph, request_probe, order_book_probe = _probe_system()
        resolver = LocalInputResolver()

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(
                registry=registry,
                graph_definition=graph,
                input_resolver=resolver,
                report_store=store,
            ).run(
                _request(),
                input_snapshots=[_order_book().to_input_snapshot(horizon="1h")],
            )
            run = store.load_run(report.run_id or "")

        self.assertEqual(
            request_probe.received_bundles[0].required_input_kinds,
            ("analysis_request",),
        )
        self.assertEqual(
            order_book_probe.received_bundles[0].required_input_kinds,
            ("analysis_request", "order_book_snapshot"),
        )
        self.assertEqual(report.decision.metadata["order_book_sequence"], 42)
        self.assertAlmostEqual(
            report.decision.score,
            _order_book().spread_bps,
        )
        self.assertEqual(resolver.resolve_count, 2)
        self.assertEqual(len(run["metadata"]["input_resolution_records"]), 3)
        self.assertEqual(run["schema_version"], "analysis_run.v2")
        self.assertEqual(
            [item["input_kind"] for item in run["input_snapshots"]],
            ["analysis_request", "order_book_snapshot"],
        )
        self.assertEqual(len(run["metadata"]["input_snapshot_audits"]), 2)
        traces_by_cell = {
            trace["cell_id"]: trace
            for trace in run["metadata"]["cell_runtime_traces"]
        }
        self.assertEqual(
            traces_by_cell["test.request_probe"]["metadata"]["input_kinds"],
            ["analysis_request"],
        )
        self.assertEqual(
            traces_by_cell["test.order_book_probe"]["metadata"]["input_kinds"],
            ["analysis_request", "order_book_snapshot"],
        )
        self.assertEqual(
            traces_by_cell["test.order_book_probe"]["metadata"][
                "input_bundle_schema_version"
            ],
            "cell_input_bundle.v1",
        )

    def test_engine_rejects_extra_input_scope_and_kind_ambiguity(self):
        registry, graph, _, _ = _probe_system()
        engine = AnalysisEngine(registry=registry, graph_definition=graph)
        snapshot = _order_book().to_input_snapshot(horizon="1h")

        with self.assertRaisesRegex(InputCompositionError, "scope"):
            engine.run(_request(), input_snapshots=[replace(snapshot, horizon="4h")])
        with self.assertRaisesRegex(InputCompositionError, "one extra snapshot"):
            engine.run(_request(), input_snapshots=[snapshot, snapshot])

    def test_multi_input_analysis_run_replays_all_snapshots_stably(self):
        registry, graph, _, _ = _probe_system()

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(
                registry=registry,
                graph_definition=graph,
                report_store=store,
            ).run(
                _request(),
                input_snapshots=[_order_book().to_input_snapshot(horizon="1h")],
            )
            comparison = ReplayRunner(
                store,
                engine_factory=_probe_engine,
            ).replay(report.report_id or "")

        self.assertTrue(comparison.input_hash_matches)
        self.assertTrue(comparison.result_stable)
        self.assertEqual(comparison.drift_fields, [])


class CellInputBundleTests(unittest.TestCase):
    def test_bundle_rejects_more_than_one_snapshot_for_a_required_kind(self):
        request = _request()
        request_snapshot = InputSnapshot.from_analysis_request(request)
        first = _order_book().to_input_snapshot(horizon=request.horizon)
        second_book = replace(
            _order_book(),
            provenance=replace(
                _order_book().provenance,
                source_provider="backup.websocket",
            ),
        )
        second = second_book.to_input_snapshot(horizon=request.horizon)

        with self.assertRaisesRegex(ValueError, "kinds do not match"):
            CellInputBundle(
                node_id="node:test",
                analysis_request=request,
                resolved_inputs=(
                    ResolvedCellInput(
                        reference=request_snapshot.to_reference(),
                        snapshot=request_snapshot,
                    ),
                    ResolvedCellInput(reference=first.to_reference(), snapshot=first),
                    ResolvedCellInput(reference=second.to_reference(), snapshot=second),
                ),
                required_input_kinds=(
                    "analysis_request",
                    "order_book_snapshot",
                ),
            )


class _ProbeCell(MarketCell):
    category = "test"
    description = "Probe typed input composition without production formula logic."
    formula_version = "typed_input_probe_v0.1"
    inputs = ["typed_input_bundle"]
    outputs = ["probe_result"]

    def __init__(self, cell_id: str, required_input_kinds: list[str]) -> None:
        self.cell_id = cell_id
        self.name = cell_id
        self.required_input_kinds = list(required_input_kinds)
        self.received_bundles: list[CellInputBundle] = []

    def analyze_inputs(self, inputs, child_results=None):
        self.received_bundles.append(inputs)
        order_book = None
        if "order_book_snapshot" in self.required_input_kinds:
            order_book = OrderBookSnapshot.from_input_snapshot(
                inputs.require_one("order_book_snapshot")
            )
        return CellResult(
            cell_id=self.cell_id,
            name=self.name,
            category=self.category,
            target=inputs.analysis_request.target,
            horizon=inputs.analysis_request.horizon,
            direction="neutral",
            strength=0,
            confidence=100,
            volatility_risk=0,
            manipulation_risk=0,
            urgency=0,
            score=order_book.spread_bps if order_book is not None else 0,
            explanation="typed input probe",
            children=list(child_results or []),
            metadata={
                "input_kinds": list(inputs.required_input_kinds),
                "order_book_sequence": (
                    order_book.provenance.sequence
                    if order_book is not None
                    else None
                ),
            },
        )

    def analyze(self, request, child_results=None):
        raise AssertionError("planned execution must use analyze_inputs")


def _probe_system():
    request_probe = _ProbeCell("test.request_probe", ["analysis_request"])
    order_book_probe = _ProbeCell(
        "test.order_book_probe",
        ["analysis_request", "order_book_snapshot"],
    )
    graph = CellGraphDefinition(
        graph_id="test.typed_inputs",
        graph_version="1.0.0",
        name="Typed Input Probe",
        root_node_id="node:order_book",
        nodes=[
            CellGraphNode(
                node_id="node:request",
                cell_id=request_probe.cell_id,
                execution_role="leaf",
            ),
            CellGraphNode(
                node_id="node:order_book",
                cell_id=order_book_probe.cell_id,
                execution_role="root",
                dependencies=["node:request"],
            ),
        ],
    )
    return (
        CellRegistry([request_probe, order_book_probe]),
        graph,
        request_probe,
        order_book_probe,
    )


def _probe_engine() -> AnalysisEngine:
    registry, graph, _, _ = _probe_system()
    return AnalysisEngine(registry=registry, graph_definition=graph)


def _order_book() -> OrderBookSnapshot:
    return OrderBookSnapshot(
        target="BTC/USD",
        bids=[
            OrderBookLevel(100.0, 1.25, 3),
            OrderBookLevel(99.5, 2.5, 5),
        ],
        asks=[
            OrderBookLevel(100.5, 1.1, 2),
            OrderBookLevel(101.0, 3.0, 6),
        ],
        provenance=DataProvenance(
            source_provider="binance.websocket",
            venue="binance",
            market_type="spot",
            event_time_ms=1_721_234_567_000,
            fetched_at_ms=1_721_234_567_025,
            sequence=42,
            source_event_id="depth-42",
            quality_flags=[],
        ),
        metadata={"depth": 2},
    )


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        target="BTC/USD",
        horizon="1h",
        candles=[
            Candle("t1", 100, 102, 99, 101, 1000),
            Candle("t2", 101, 104, 100, 103, 1200),
        ],
    )


def _replace_node(plan, replacement):
    return [
        replacement if node.node_id == replacement.node_id else node
        for node in plan.nodes
    ]


def _validation_codes(plan):
    try:
        validate_execution_plan(plan)
    except ExecutionPlanValidationError as exc:
        return {issue.code for issue in exc.issues}
    raise AssertionError("expected ExecutionPlanValidationError")


if __name__ == "__main__":
    unittest.main()
