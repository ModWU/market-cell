from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_cell.engine import AnalysisEngine
from market_cell.events import EventBus
from market_cell.execution import (
    FileSystemRuntimeSummaryStore,
    InMemoryRuntimeSummaryStore,
    RuntimeSummarySnapshot,
)
from market_cell.execution.models import CellRuntimeTrace
from market_cell.models import AnalysisRequest, Candle
from market_cell.registry import default_registry
from market_cell.graph import default_analysis_graph
from market_cell.reports import FileSystemReportStore


AS_OF = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)


class RuntimeSummaryStoreTests(unittest.TestCase):
    def test_snapshot_aggregates_only_the_explicit_time_window(self):
        store = InMemoryRuntimeSummaryStore()
        store.save_traces(
            [
                _trace("run-1", "span-1", 10, "succeeded", hour=8),
                _trace("run-2", "span-2", 20, "failed", hour=10, retry_count=2),
                _trace("run-2", "span-3", 40, "succeeded", hour=11),
                _trace(
                    "run-old",
                    "span-old",
                    100,
                    "failed",
                    day=14,
                ),
                _trace(
                    "run-v2",
                    "span-v2",
                    5,
                    "succeeded",
                    hour=9,
                    formula_version="trend.v2",
                    implementation_id="python-local:technical.trend:trend.v2",
                ),
            ]
        )

        snapshot = store.snapshot(window=timedelta(days=1), as_of=AS_OF)

        self.assertEqual(snapshot.trace_count, 4)
        self.assertEqual(len(snapshot.entries), 2)
        history = next(
            entry for entry in snapshot.entries if entry.formula_version == "trend.v1"
        )
        self.assertEqual(history.trace_count, 3)
        self.assertEqual(history.run_count, 2)
        self.assertEqual(history.succeeded_count, 2)
        self.assertEqual(history.failed_count, 1)
        self.assertEqual(history.retried_trace_count, 1)
        self.assertEqual(history.failure_rate, 0.333333)
        self.assertEqual(history.retry_rate, 0.333333)
        self.assertEqual(history.average_duration_ms, 23.333333)
        self.assertEqual(history.p50_duration_ms, 20)
        self.assertEqual(history.p95_duration_ms, 40)
        self.assertEqual(history.p99_duration_ms, 40)
        self.assertEqual(history.retry_count, 2)
        self.assertEqual(history.latest_status, "succeeded")
        self.assertEqual(
            history.latest_finished_at,
            "2026-07-16T11:00:00+00:00",
        )

    def test_filesystem_store_is_idempotent_and_survives_reopen(self):
        traces = [
            _trace("run-1", "span-1", 10, "succeeded", hour=8),
            _trace("run-2", "span-2", 20, "failed", hour=10),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemRuntimeSummaryStore(Path(temp_dir))
            first = store.save_traces([traces[0], traces[0], traces[1]])
            second = store.save_traces(traces)
            reopened = FileSystemRuntimeSummaryStore(Path(temp_dir))
            snapshot = reopened.snapshot(window=timedelta(days=1), as_of=AS_OF)

        self.assertEqual(first.stored_trace_count, 2)
        self.assertEqual(first.duplicate_trace_count, 1)
        self.assertEqual(second.stored_trace_count, 0)
        self.assertEqual(second.duplicate_trace_count, 2)
        self.assertEqual(snapshot.trace_count, 2)
        self.assertEqual(snapshot.entries[0].failure_rate, 0.5)

    def test_canceled_attempt_is_stored_but_excluded_from_placement_snapshot(self):
        store = InMemoryRuntimeSummaryStore()
        canceled = replace(
            _trace("run-canceled", "span-canceled", 12, "failed", hour=9),
            metadata={
                "execution_control": {
                    "failure_kind": "canceled",
                    "placement_eligible": False,
                }
            },
        )

        write = store.save_traces([canceled])
        snapshot = store.snapshot(window=timedelta(days=1), as_of=AS_OF)

        self.assertEqual(write.stored_trace_count, 1)
        self.assertEqual(snapshot.trace_count, 0)
        self.assertEqual(snapshot.entries, [])

    def test_engine_uses_previous_runs_and_audits_store_writes(self):
        runtime_store = InMemoryRuntimeSummaryStore()
        engine = AnalysisEngine(runtime_summary_store=runtime_store)

        engine.run(_request())
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = FileSystemReportStore(Path(temp_dir))
            engine.report_store = report_store
            report = engine.run(_request())
            run = report_store.load_run(report.run_id or "")

        snapshot = run["metadata"]["runtime_summary_snapshot"]
        write = run["metadata"]["runtime_summary_write"]
        plan_snapshot = run["metadata"]["cell_execution_plan"]["metadata"][
            "runtime_summary_snapshot"
        ]
        expected_trace_count = len(default_analysis_graph().nodes)
        self.assertEqual(snapshot["trace_count"], expected_trace_count)
        self.assertEqual(plan_snapshot["snapshot_id"], snapshot["snapshot_id"])
        self.assertEqual(write["status"], "succeeded")
        self.assertEqual(write["attempted_trace_count"], expected_trace_count)
        self.assertEqual(write["stored_trace_count"], expected_trace_count)

    def test_failed_run_still_records_partial_runtime_history(self):
        registry = default_registry()
        failing_cell = registry.resolve("technical.trend")
        runtime_store = InMemoryRuntimeSummaryStore()
        event_bus = EventBus()

        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = FileSystemReportStore(Path(temp_dir))
            with patch.object(
                failing_cell,
                "analyze",
                side_effect=RuntimeError("cell failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "cell failed"):
                    AnalysisEngine(
                        registry=registry,
                        report_store=report_store,
                        runtime_summary_store=runtime_store,
                        event_bus=event_bus,
                    ).run(_request())
            failed_event = next(
                event for event in event_bus.events if event.name == "analysis.failed"
            )
            run = report_store.load_run(failed_event.payload["run_id"])

        snapshot = runtime_store.snapshot(window=timedelta(days=1))
        self.assertGreater(snapshot.trace_count, 0)
        self.assertTrue(any(entry.failed_count for entry in snapshot.entries))
        self.assertEqual(run["metadata"]["runtime_summary_write"]["status"], "succeeded")

    def test_runtime_store_write_failure_does_not_fail_analysis(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = FileSystemReportStore(Path(temp_dir))
            report = AnalysisEngine(
                report_store=report_store,
                runtime_summary_store=_FailingWriteStore(),
            ).run(_request())
            run = report_store.load_run(report.run_id or "")

        write = run["metadata"]["runtime_summary_write"]
        self.assertEqual(write["status"], "failed")
        self.assertIn("history unavailable", write["error"])

    def test_runtime_window_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "must be positive"):
            AnalysisEngine(runtime_summary_window=timedelta(0))


class _FailingWriteStore:
    @property
    def name(self) -> str:
        return "failing-runtime-summary-store"

    def snapshot(self, *, window, as_of=None):
        return RuntimeSummarySnapshot.empty(
            window=window,
            as_of=as_of,
            store=self.name,
        )

    def save_traces(self, traces):
        raise RuntimeError("history unavailable")


def _trace(
    run_id: str,
    span_id: str,
    duration_ms: float,
    status,
    *,
    day: int = 16,
    hour: int = 8,
    retry_count: int = 0,
    formula_version: str = "trend.v1",
    implementation_id: str = "python-local:technical.trend:trend.v1",
) -> CellRuntimeTrace:
    finished_at = datetime(2026, 7, day, hour, tzinfo=timezone.utc).isoformat()
    return CellRuntimeTrace(
        trace_id=f"trace-{run_id}",
        span_id=span_id,
        run_id=run_id,
        node_id="cell:technical.trend",
        cell_id="technical.trend",
        formula_version=formula_version,
        status=status,
        started_at=finished_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        plan_id=f"plan-{run_id}",
        implementation_id=implementation_id,
        service_id="python-local",
        runtime="python_local",
        retry_count=retry_count,
        error="boom" if status == "failed" else None,
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
