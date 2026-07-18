from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_cell.engine import AnalysisEngine
from market_cell.events import EventBus, utc_now_iso
from market_cell.execution import (
    CellExecutionContext,
    CellExecutionOutcome,
    CellRuntimeTrace,
    ExecutionTraceMismatchError,
    ExecutorDispatchError,
    ExecutorRouteNotFoundError,
    ExecutorRouter,
    LocalCellExecutor,
    ServiceCapabilityCatalog,
    build_local_capability_catalog,
    build_local_execution_plan,
)
from market_cell.models import AnalysisRequest, Candle
from market_cell.registry import default_registry
from market_cell.reports import FileSystemReportStore


class ExecutorRouterTests(unittest.TestCase):
    def test_exact_service_route_wins_over_runtime_route(self):
        cell, request, context = _remote_execution_context()
        service_executor = _BindingAwareExecutor("rust-service-executor")
        runtime_executor = _BindingAwareExecutor("generic-rust-executor")
        router = ExecutorRouter(
            service_routes={"rust-hot": service_executor},
            runtime_routes={"rust_service": runtime_executor},
        )

        outcome = router.execute(cell=cell, request=request, context=context)

        self.assertEqual(outcome.unwrap().cell_id, cell.cell_id)
        self.assertEqual(service_executor.call_count, 1)
        self.assertEqual(runtime_executor.call_count, 0)
        self.assertEqual(outcome.trace.service_id, "rust-hot")
        self.assertEqual(outcome.trace.metadata["route_kind"], "service")
        self.assertEqual(outcome.trace.metadata["route_key"], "rust-hot")
        self.assertEqual(
            outcome.trace.metadata["routed_executor"],
            "rust-service-executor",
        )

    def test_runtime_route_handles_service_without_exact_registration(self):
        cell, request, context = _remote_execution_context()
        executor = _BindingAwareExecutor("generic-rust-executor")
        router = ExecutorRouter(runtime_routes={"rust_service": executor})

        outcome = router.execute(cell=cell, request=request, context=context)

        self.assertEqual(outcome.unwrap().cell_id, cell.cell_id)
        self.assertEqual(executor.call_count, 1)
        self.assertEqual(outcome.trace.metadata["route_kind"], "runtime")
        self.assertEqual(outcome.trace.metadata["route_key"], "rust_service")

    def test_missing_route_fails_before_cell_execution_and_keeps_planned_binding(self):
        cell, request, context = _remote_execution_context()
        router = ExecutorRouter(runtime_routes={"python_local": LocalCellExecutor()})

        with patch.object(cell, "analyze", wraps=cell.analyze) as analyze:
            outcome = router.execute(cell=cell, request=request, context=context)

        analyze.assert_not_called()
        self.assertIsInstance(outcome.error, ExecutorRouteNotFoundError)
        self.assertEqual(outcome.trace.status, "failed")
        self.assertIsNone(outcome.trace.implementation_id)
        self.assertIsNone(outcome.trace.service_id)
        self.assertIsNone(outcome.trace.runtime)
        self.assertEqual(outcome.trace.metadata["execution_phase"], "routing")
        self.assertEqual(outcome.trace.metadata["planned_service_id"], "rust-hot")
        self.assertEqual(outcome.trace.metadata["route_status"], "failed")

    def test_delegate_exception_becomes_auditable_dispatch_failure(self):
        cell, request, context = _remote_execution_context()
        executor = _BindingAwareExecutor(
            "raising-rust-executor",
            exception=RuntimeError("transport unavailable"),
        )
        router = ExecutorRouter(service_routes={"rust-hot": executor})

        outcome = router.execute(cell=cell, request=request, context=context)

        self.assertIsInstance(outcome.error, ExecutorDispatchError)
        self.assertEqual(outcome.trace.status, "failed")
        self.assertIsNone(outcome.trace.service_id)
        self.assertEqual(outcome.trace.metadata["execution_phase"], "dispatch")
        self.assertEqual(outcome.trace.metadata["route_status"], "dispatch_failed")
        self.assertEqual(outcome.trace.metadata["cause_type"], "RuntimeError")

    def test_router_rejects_delegate_trace_that_does_not_match_planned_binding(self):
        cell, request, context = _remote_execution_context()
        executor = _BindingAwareExecutor(
            "drifted-rust-executor",
            trace_service_id="unexpected-service",
        )
        router = ExecutorRouter(service_routes={"rust-hot": executor})

        outcome = router.execute(cell=cell, request=request, context=context)

        self.assertIsInstance(outcome.error, ExecutionTraceMismatchError)
        self.assertEqual(outcome.trace.status, "failed")
        self.assertEqual(outcome.trace.service_id, "unexpected-service")
        self.assertEqual(outcome.trace.metadata["route_status"], "trace_rejected")
        self.assertEqual(outcome.trace.metadata["delegate_status"], "succeeded")
        with self.assertRaises(ExecutionTraceMismatchError):
            outcome.unwrap()

    def test_router_rejects_delegate_trace_with_drifted_run_identity(self):
        cell, request, context = _remote_execution_context()
        executor = _BindingAwareExecutor(
            "drifted-run-executor",
            trace_run_id="unexpected-run",
        )
        router = ExecutorRouter(service_routes={"rust-hot": executor})

        outcome = router.execute(cell=cell, request=request, context=context)

        self.assertIsInstance(outcome.error, ExecutionTraceMismatchError)
        self.assertIn("run_id", str(outcome.error))
        self.assertEqual(outcome.trace.metadata["route_status"], "trace_rejected")

    def test_analysis_engine_executes_mixed_catalog_through_router(self):
        registry, catalog, rust_trend = _mixed_catalog()
        remote_executor = _BindingAwareExecutor("rust-service-executor")
        router = ExecutorRouter(
            service_routes={"rust-hot": remote_executor},
            runtime_routes={"python_local": LocalCellExecutor()},
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(
                registry=registry,
                executor=router,
                capability_catalog=catalog,
                report_store=store,
            ).run(_request())
            run = store.load_run(report.run_id or "")

        trend_trace = next(
            trace
            for trace in run["metadata"]["cell_runtime_traces"]
            if trace["cell_id"] == "technical.trend"
        )
        trend_node = next(
            node
            for node in run["metadata"]["cell_execution_plan"]["nodes"]
            if node["cell_id"] == "technical.trend"
        )
        self.assertEqual(remote_executor.call_count, 1)
        self.assertEqual(trend_trace["service_id"], "rust-hot")
        self.assertEqual(trend_trace["runtime"], "rust_service")
        self.assertEqual(trend_trace["metadata"]["route_kind"], "service")
        self.assertEqual(trend_node["binding_id"], rust_trend.binding_id)
        self.assertTrue(
            all(
                trace["metadata"]["executor_router"] == "executor_router_v0.1"
                for trace in run["metadata"]["cell_runtime_traces"]
            )
        )

    def test_analysis_engine_persists_router_failure_trace(self):
        registry, catalog, _ = _mixed_catalog()
        catalog = ServiceCapabilityCatalog.create(
            [
                binding
                for binding in catalog.bindings
                if not (
                    binding.cell_id == "technical.trend"
                    and binding.service_id == "python-local"
                )
            ],
            catalog_id="remote-trend-without-fallback",
        )
        event_bus = EventBus()
        router = ExecutorRouter(
            runtime_routes={"python_local": LocalCellExecutor()},
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            with self.assertRaises(ExecutorRouteNotFoundError):
                AnalysisEngine(
                    registry=registry,
                    executor=router,
                    capability_catalog=catalog,
                    event_bus=event_bus,
                    report_store=store,
                ).run(_request())
            failed_event = next(
                event for event in event_bus.events if event.name == "analysis.failed"
            )
            run = store.load_run(failed_event.payload["run_id"])

        failed_trace = run["metadata"]["cell_runtime_traces"][-1]
        self.assertEqual(run["status"], "failed")
        self.assertEqual(failed_trace["status"], "failed")
        self.assertIsNone(failed_trace["service_id"])
        self.assertEqual(
            failed_trace["metadata"]["planned_service_id"],
            "rust-hot",
        )
        self.assertEqual(
            run["metadata"]["plan_execution"]["failed_node_id"],
            "cell:technical.trend",
        )


class _BindingAwareExecutor:
    def __init__(
        self,
        name: str,
        *,
        exception: Exception | None = None,
        trace_service_id: str | None = None,
        trace_run_id: str | None = None,
    ) -> None:
        self._name = name
        self.exception = exception
        self.trace_service_id = trace_service_id
        self.trace_run_id = trace_run_id
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    def execute(self, **kwargs) -> CellExecutionOutcome:
        self.call_count += 1
        if self.exception is not None:
            raise self.exception
        cell = kwargs["cell"]
        request = kwargs["request"]
        context = kwargs["context"]
        binding = context.binding
        node = context.node
        if binding is None or node is None:
            raise AssertionError("test executor requires a planned binding")
        result = cell.analyze(request, kwargs.get("child_results"))
        timestamp = utc_now_iso()
        return CellExecutionOutcome(
            result=result,
            trace=CellRuntimeTrace(
                trace_id=context.trace_id,
                span_id=f"span-{self.call_count}",
                run_id=self.trace_run_id or context.run_id,
                plan_id=context.plan_id,
                node_id=node.node_id,
                cell_id=node.cell_id,
                formula_version=node.formula_version,
                implementation_id=binding.implementation_id,
                service_id=self.trace_service_id or binding.service_id,
                runtime=binding.runtime,
                status="succeeded",
                started_at=timestamp,
                finished_at=timestamp,
                duration_ms=0.1,
                metadata={"executor": self.name},
            ),
        )


def _remote_execution_context():
    registry = default_registry()
    request = _request()
    plan = build_local_execution_plan(registry, request)
    cell = registry.resolve("technical.trend")
    local_node = next(node for node in plan.nodes if node.cell_id == cell.cell_id)
    local_binding = next(
        binding
        for binding in plan.service_bindings
        if binding.binding_id == local_node.binding_id
    )
    remote_binding = replace(
        local_binding,
        implementation_id=f"rust-hot:{cell.cell_id}:{cell.formula_version}",
        service_id="rust-hot",
        runtime="rust_service",
        language="rust",
        task_queue="cell.rust-hot",
    )
    remote_node = replace(local_node, binding_id=remote_binding.binding_id)
    return (
        cell,
        request,
        CellExecutionContext(
            run_id="test-run",
            trace_id="test-trace",
            plan_id=plan.plan_id,
            node=remote_node,
            binding=remote_binding,
        ),
    )


def _mixed_catalog():
    registry = default_registry()
    local_catalog = build_local_capability_catalog(registry)
    local_trend = next(
        binding
        for binding in local_catalog.bindings
        if binding.cell_id == "technical.trend"
    )
    rust_trend = replace(
        local_trend,
        implementation_id=(
            f"rust-hot:{local_trend.cell_id}:{local_trend.formula_version}"
        ),
        service_id="rust-hot",
        runtime="rust_service",
        language="rust",
        task_queue="cell.rust-hot",
        priority=10,
    )
    return (
        registry,
        ServiceCapabilityCatalog.create(
            [*local_catalog.bindings, rust_trend],
            catalog_id="mixed-executor-catalog",
        ),
        rust_trend,
    )


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        target="BTC/USD",
        horizon="1h",
        candles=[
            Candle("t1", 100, 102, 99, 101, 1000),
            Candle("t2", 101, 104, 100, 103, 1200),
            Candle("t3", 103, 106, 102, 105, 1400),
        ],
    )


if __name__ == "__main__":
    unittest.main()
