from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from market_cell.engine import AnalysisEngine
from market_cell.events import EventBus, utc_now_iso
from market_cell.execution import (
    CancellationToken,
    CellExecutionBackpressureError,
    CellExecutionContext,
    CellExecutionOutcome,
    CellExecutionTimeoutError,
    CellRuntimeTrace,
    ExecutorDispatchError,
    ExecutorRouter,
    ExecutionControlMismatchError,
    ExecutionTraceMismatchError,
    FailureControlledExecutor,
    IDEMPOTENT_EXECUTION_CAPABILITY,
    InMemoryConcurrencyAdmissionController,
    LocalCellExecutor,
    ResourceHints,
    execution_attempt_id,
    execution_idempotency_key,
    validate_execution_trace,
    validate_execution_control_record,
)
from market_cell.models import AnalysisRequest, Candle
from market_cell.inputs import CellInputBundle, InputSnapshot, ResolvedCellInput
from market_cell.registry import default_registry
from market_cell.graph import default_analysis_graph
from market_cell.reports import FileSystemReportStore


ROOT = Path(__file__).resolve().parents[3]


class ExecutionControlTests(unittest.TestCase):
    def test_identity_matches_cross_language_vector(self):
        vector = json.loads(
            (
                ROOT / "contracts" / "test_vectors" / "execution_identity_v1.json"
            ).read_text(encoding="utf-8")
        )
        data = vector["input"]
        _, _, context = _local_context()
        context = replace(
            context,
            run_id=data["run_id"],
            plan_id=data["plan_id"],
            node=replace(
                context.node,
                node_id=data["node_id"],
                binding_id=data["binding_id"],
            ),
        )

        idempotency_key = execution_idempotency_key(context)

        self.assertEqual(
            idempotency_key,
            vector["expected"]["idempotency_key"],
        )
        self.assertEqual(
            [
                execution_attempt_id(
                    idempotency_key,
                    data["binding_id"],
                    attempt_number,
                )
                for attempt_number in (1, 2)
            ],
            vector["expected"]["attempt_ids"],
        )

    def test_dispatch_failure_retries_with_same_idempotency_key(self):
        cell, request, context = _local_context(
            resource_hints=ResourceHints(max_retries=1),
        )
        executor = _SequenceExecutor(
            [ExecutorDispatchError("temporary transport failure"), None]
        )

        outcome = FailureControlledExecutor(executor).execute(
            cell=cell,
            request=request,
            context=context,
        )

        self.assertEqual(outcome.unwrap().cell_id, cell.cell_id)
        self.assertEqual(executor.call_count, 2)
        self.assertEqual(len(outcome.runtime_traces), 2)
        self.assertEqual([trace.status for trace in outcome.runtime_traces], ["failed", "succeeded"])
        self.assertEqual([trace.retry_count for trace in outcome.runtime_traces], [0, 1])
        record = outcome.control_record
        self.assertIsNotNone(record)
        self.assertEqual(record.retry_count, 1)
        self.assertEqual(record.fallback_count, 0)
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(
            {attempt.idempotency_key for attempt in record.attempts},
            {record.idempotency_key},
        )
        self.assertEqual(
            [attempt.binding_attempt_number for attempt in record.attempts],
            [1, 2],
        )
        with self.assertRaises(ExecutionControlMismatchError):
            validate_execution_control_record(
                replace(record, control_id="drifted-control-id"),
                context,
                outcome.runtime_traces,
            )

    def test_late_result_is_rejected_as_timeout_then_retried(self):
        cell, request, context = _local_context(
            resource_hints=ResourceHints(expected_timeout_ms=5, max_retries=1),
        )
        executor = _SequenceExecutor([None, None], durations_ms=[20.0, 1.0])

        outcome = FailureControlledExecutor(executor).execute(
            cell=cell,
            request=request,
            context=context,
        )

        self.assertEqual(outcome.unwrap().cell_id, cell.cell_id)
        self.assertEqual(outcome.runtime_traces[0].status, "failed")
        self.assertIn("exceeded timeout", outcome.runtime_traces[0].error or "")
        self.assertEqual(
            [attempt.status for attempt in outcome.control_record.attempts],
            ["timed_out", "succeeded"],
        )
        self.assertEqual(outcome.control_record.retry_count, 1)

    def test_unknown_execution_failure_is_not_retried(self):
        cell, request, context = _local_context(
            resource_hints=ResourceHints(max_retries=3),
        )
        executor = _SequenceExecutor([RuntimeError("formula failed"), None])

        outcome = FailureControlledExecutor(executor).execute(
            cell=cell,
            request=request,
            context=context,
        )

        self.assertIsInstance(outcome.error, RuntimeError)
        self.assertEqual(executor.call_count, 1)
        self.assertEqual(outcome.control_record.retry_count, 0)
        self.assertEqual(outcome.control_record.final_failure_kind, "execution")

    def test_stateful_timeout_requires_explicit_idempotent_capability_to_retry(self):
        hints = ResourceHints(
            stateful=True,
            expected_timeout_ms=5,
            max_retries=1,
        )
        cell, request, context = _local_context(resource_hints=hints)
        unsafe_executor = _SequenceExecutor([None, None], durations_ms=[20.0, 1.0])

        unsafe_outcome = FailureControlledExecutor(unsafe_executor).execute(
            cell=cell,
            request=request,
            context=context,
        )

        self.assertIsInstance(unsafe_outcome.error, CellExecutionTimeoutError)
        self.assertEqual(unsafe_executor.call_count, 1)
        self.assertFalse(unsafe_outcome.control_record.attempts[0].retryable)

        safe_binding = replace(
            context.binding,
            capabilities=[
                *context.binding.capabilities,
                IDEMPOTENT_EXECUTION_CAPABILITY,
            ],
        )
        safe_context = replace(context, binding=safe_binding)
        safe_executor = _SequenceExecutor([None, None], durations_ms=[20.0, 1.0])

        safe_outcome = FailureControlledExecutor(safe_executor).execute(
            cell=cell,
            request=request,
            context=safe_context,
        )

        self.assertEqual(safe_outcome.unwrap().cell_id, cell.cell_id)
        self.assertEqual(safe_executor.call_count, 2)

    def test_retry_budget_is_exhausted_before_explicit_fallback(self):
        cell, request, context = _local_context(
            resource_hints=ResourceHints(max_retries=1),
        )
        primary = replace(context.binding, service_id="python-primary")
        fallback = replace(
            context.binding,
            service_id="python-fallback",
            resource_hints=ResourceHints(max_retries=0),
        )
        node = replace(
            context.node,
            binding_id=primary.binding_id,
            fallback_binding_ids=[fallback.binding_id],
        )
        context = replace(
            context,
            node=node,
            binding=primary,
            fallback_bindings=(fallback,),
        )
        executor = _SequenceExecutor(
            [
                ExecutorDispatchError("primary unavailable"),
                ExecutorDispatchError("primary still unavailable"),
                None,
            ]
        )

        outcome = FailureControlledExecutor(executor).execute(
            cell=cell,
            request=request,
            context=context,
        )

        self.assertEqual(outcome.unwrap().cell_id, cell.cell_id)
        record = outcome.control_record
        self.assertEqual(
            [attempt.binding_id for attempt in record.attempts],
            [primary.binding_id, primary.binding_id, fallback.binding_id],
        )
        self.assertEqual(
            [attempt.fallback_index for attempt in record.attempts],
            [0, 0, 1],
        )
        self.assertEqual(record.retry_count, 1)
        self.assertEqual(record.fallback_count, 1)

    def test_cancellation_before_attempt_does_not_call_executor(self):
        cell, request, context = _local_context()
        token = CancellationToken()
        token.cancel()
        context = replace(context, cancellation_signal=token)
        executor = _SequenceExecutor([None])

        outcome = FailureControlledExecutor(executor).execute(
            cell=cell,
            request=request,
            context=context,
        )

        self.assertEqual(executor.call_count, 0)
        self.assertEqual(outcome.control_record.status, "canceled")
        self.assertEqual(outcome.control_record.final_failure_kind, "canceled")
        self.assertEqual(outcome.trace.status, "failed")
        self.assertIsNone(outcome.trace.service_id)

    def test_backpressure_rejects_before_executor_and_is_audited(self):
        cell, request, context = _local_context(max_concurrency=1)
        admission = InMemoryConcurrencyAdmissionController()
        occupied = admission.try_acquire(context.binding)
        self.assertIsNotNone(occupied)
        executor = _SequenceExecutor([None])
        try:
            outcome = FailureControlledExecutor(
                executor,
                admission_controller=admission,
            ).execute(cell=cell, request=request, context=context)
        finally:
            occupied.release()

        self.assertIsInstance(outcome.error, CellExecutionBackpressureError)
        self.assertEqual(executor.call_count, 0)
        self.assertEqual(outcome.control_record.attempts[0].status, "backpressured")
        self.assertEqual(outcome.control_record.final_failure_kind, "backpressure")
        self.assertIsNone(outcome.trace.service_id)

    def test_explicit_fallback_uses_only_plan_binding_and_keeps_both_traces(self):
        registry = default_registry()
        request = _request()
        plan = _local_plan(request)
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
        fallback_node = replace(
            local_node,
            binding_id=remote_binding.binding_id,
            fallback_binding_ids=[local_binding.binding_id],
            resource_hints=remote_binding.resource_hints,
        )
        fallback_plan = replace(
            plan,
            nodes=[
                fallback_node if node.node_id == fallback_node.node_id else node
                for node in plan.nodes
            ],
            service_bindings=[*plan.service_bindings, remote_binding],
        )
        context = CellExecutionContext(
            run_id="fallback-run",
            trace_id="fallback-trace",
            plan_id=fallback_plan.plan_id,
            node=fallback_node,
            binding=remote_binding,
            input_bundle=_input_bundle(fallback_node, request, fallback_plan),
            fallback_bindings=(local_binding,),
        )
        router = ExecutorRouter(
            runtime_routes={"python_local": LocalCellExecutor()},
        )

        outcome = FailureControlledExecutor(router).execute(
            cell=cell,
            request=request,
            context=context,
        )

        self.assertEqual(outcome.unwrap().cell_id, cell.cell_id)
        self.assertEqual(len(outcome.runtime_traces), 2)
        self.assertIsNone(outcome.runtime_traces[0].service_id)
        self.assertEqual(outcome.runtime_traces[1].service_id, "python-local")
        self.assertEqual(outcome.control_record.fallback_count, 1)
        self.assertEqual(outcome.control_record.final_binding_id, local_binding.binding_id)
        self.assertEqual(
            [attempt.failure_kind for attempt in outcome.control_record.attempts],
            ["routing", None],
        )
        for trace in outcome.runtime_traces:
            validate_execution_trace(trace, fallback_plan)
        unaudited_fallback_trace = replace(
            outcome.runtime_traces[1],
            metadata={
                key: value
                for key, value in outcome.runtime_traces[1].metadata.items()
                if key != "execution_control"
            },
        )
        with self.assertRaises(ExecutionTraceMismatchError):
            validate_execution_trace(unaudited_fallback_trace, fallback_plan)

    def test_analysis_engine_persists_control_record_for_every_node(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(report_store=store).run(_request())
            run = store.load_run(report.run_id or "")

        records = run["metadata"]["execution_control_records"]
        self.assertEqual(len(records), len(default_analysis_graph().nodes))
        self.assertTrue(all(record["status"] == "succeeded" for record in records))
        self.assertTrue(all(len(record["attempts"]) == 1 for record in records))
        self.assertTrue(all(record["idempotency_key"] for record in records))

    def test_analysis_engine_cancellation_is_persisted(self):
        token = CancellationToken()
        token.cancel()
        event_bus = EventBus()

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            with self.assertRaisesRegex(Exception, "canceled before attempt"):
                AnalysisEngine(
                    event_bus=event_bus,
                    report_store=store,
                ).run(_request(), cancellation_signal=token)
            failed_event = next(
                event for event in event_bus.events if event.name == "analysis.failed"
            )
            run = store.load_run(failed_event.payload["run_id"])

        self.assertEqual(run["status"], "failed")
        self.assertEqual(
            run["metadata"]["execution_control_records"][0]["status"],
            "canceled",
        )
        self.assertEqual(
            run["metadata"]["execution_control_records"][0][
                "final_failure_kind"
            ],
            "canceled",
        )

    def test_resource_hints_reject_invalid_control_limits(self):
        with self.assertRaises(ValueError):
            ResourceHints(expected_timeout_ms=0)
        with self.assertRaises(ValueError):
            ResourceHints(max_retries=-1)
        _, _, context = _local_context()
        with self.assertRaises(ValueError):
            replace(context.binding, max_concurrency=0)


class _SequenceExecutor:
    def __init__(
        self,
        actions: list[Exception | None],
        *,
        durations_ms: list[float] | None = None,
    ) -> None:
        self.actions = list(actions)
        self.durations_ms = list(durations_ms or [0.1] * len(actions))
        self.call_count = 0

    @property
    def name(self) -> str:
        return "sequence_executor"

    def execute(self, **kwargs) -> CellExecutionOutcome:
        action = self.actions[self.call_count]
        duration_ms = self.durations_ms[self.call_count]
        self.call_count += 1
        context = kwargs["context"]
        binding = context.binding
        node = context.node
        if binding is None or node is None:
            raise AssertionError("sequence executor requires planned context")
        timestamp = utc_now_iso()
        trace = CellRuntimeTrace(
            trace_id=context.trace_id,
            span_id=f"sequence-span-{self.call_count}",
            run_id=context.run_id,
            plan_id=context.plan_id,
            node_id=node.node_id,
            cell_id=node.cell_id,
            formula_version=node.formula_version,
            implementation_id=binding.implementation_id,
            service_id=binding.service_id,
            runtime=binding.runtime,
            status="failed" if action is not None else "succeeded",
            started_at=timestamp,
            finished_at=timestamp,
            duration_ms=duration_ms,
            error=str(action) if action is not None else None,
            metadata={"executor": self.name},
        )
        if action is not None:
            return CellExecutionOutcome(trace=trace, error=action)
        result = kwargs["cell"].analyze(
            kwargs["request"],
            kwargs.get("child_results"),
        )
        return CellExecutionOutcome(trace=trace, result=result)


def _local_context(
    *,
    resource_hints: ResourceHints | None = None,
    max_concurrency: int | None = None,
):
    request = _request()
    plan = _local_plan(request)
    cell = default_registry().resolve("technical.trend")
    node = next(node for node in plan.nodes if node.cell_id == cell.cell_id)
    binding = next(
        binding
        for binding in plan.service_bindings
        if binding.binding_id == node.binding_id
    )
    if resource_hints is not None or max_concurrency is not None:
        binding = replace(
            binding,
            resource_hints=resource_hints or binding.resource_hints,
            max_concurrency=max_concurrency,
        )
        node = replace(node, resource_hints=binding.resource_hints)
    return (
        cell,
        request,
        CellExecutionContext(
            run_id="control-run",
            trace_id="control-trace",
            plan_id=plan.plan_id,
            node=node,
            binding=binding,
            input_bundle=_input_bundle(node, request, plan),
        ),
    )


def _local_plan(request):
    from market_cell.execution import build_local_execution_plan

    return build_local_execution_plan(default_registry(), request)


def _input_bundle(node, request, plan):
    snapshot = InputSnapshot.from_analysis_request(request)
    reference = next(
        reference
        for reference in plan.input_references
        if reference.input_kind == "analysis_request"
    )
    return CellInputBundle(
        node_id=node.node_id,
        analysis_request=request,
        resolved_inputs=(
            ResolvedCellInput(reference=reference, snapshot=snapshot),
        ),
        required_input_kinds=tuple(node.required_input_kinds),
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
