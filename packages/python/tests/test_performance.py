from dataclasses import replace
from pathlib import Path
import unittest

from market_cell.engine import AnalysisEngine
from market_cell.inputs import InputSnapshot
from market_cell.performance import (
    ExpectedDecision,
    PerformanceBaseline,
    PerformanceBaselineError,
    PerformanceThresholds,
    ReferenceMeasurement,
    evaluate_performance_benchmark,
)
from market_cell.models import AnalysisRequest, Candle


ROOT = Path(__file__).resolve().parents[3]


class PerformanceBaselineTests(unittest.TestCase):
    def test_repository_baseline_is_versioned_and_resolves_fixed_input(self):
        baseline_path = ROOT / "benchmarks" / "default_analysis.json"

        baseline = PerformanceBaseline.load(baseline_path)

        self.assertEqual(baseline.schema_version, "performance_baseline.v1")
        self.assertEqual(baseline.measured_runs, 20)
        self.assertTrue(baseline.resolve_input_path(baseline_path).is_file())
        self.assertGreater(baseline.thresholds.total_p95_ms, 0)
        self.assertTrue(baseline.thresholds.rationale)

    def test_correctness_and_performance_failures_are_reported_separately(self):
        report = AnalysisEngine().run(_request())
        baseline = _baseline(report, total_p95_ms=10, node_p95_ms=1)

        result = evaluate_performance_benchmark(
            baseline,
            input_hash=baseline.input_hash,
            total_duration_samples=[20, 20, 20, 20, 20],
            node_duration_samples={
                ("cell:root.decision", "root.decision"): [2, 2, 2, 2, 2],
            },
            reports=[report] * 5,
        )

        self.assertEqual(result.correctness_failures, [])
        self.assertEqual(
            {failure.code for failure in result.performance_failures},
            {"total_p95_regression", "node_p95_regression"},
        )
        self.assertFalse(result.passed)

    def test_result_drift_does_not_appear_as_performance_regression(self):
        report = AnalysisEngine().run(_request())
        baseline = _baseline(report, total_p95_ms=100, node_p95_ms=10)
        drifted = replace(
            baseline,
            expected_decision=replace(
                baseline.expected_decision,
                direction="bearish",
            ),
        )

        result = evaluate_performance_benchmark(
            drifted,
            input_hash=drifted.input_hash,
            total_duration_samples=[1, 1, 1, 1, 1],
            node_duration_samples={
                ("cell:root.decision", "root.decision"): [0.1] * 5,
            },
            reports=[report] * 5,
        )

        self.assertIn(
            "decision_mismatch",
            {failure.code for failure in result.correctness_failures},
        )
        self.assertEqual(result.performance_failures, [])

    def test_baseline_rejects_too_few_measured_runs(self):
        report = AnalysisEngine().run(_request())
        baseline = replace(_baseline(report), measured_runs=4)

        with self.assertRaisesRegex(PerformanceBaselineError, "at least 5"):
            baseline.validate()


def _baseline(
    report,
    *,
    total_p95_ms: float = 100,
    node_p95_ms: float = 10,
) -> PerformanceBaseline:
    decision = report.decision
    return PerformanceBaseline(
        benchmark_id="test-benchmark",
        input_file="unused.json",
        input_hash=InputSnapshot.from_analysis_request(_request()).content_hash,
        warmup_runs=0,
        measured_runs=5,
        expected_node_count=1,
        thresholds=PerformanceThresholds(
            total_p95_ms=total_p95_ms,
            node_p95_ms=node_p95_ms,
            rationale="test threshold",
        ),
        expected_decision=ExpectedDecision(
            cell_id=decision.cell_id,
            direction=decision.direction,
            score=decision.score,
            risk_level=decision.risk_level,
            action_posture=decision.action_posture,
            child_count=len(decision.children),
        ),
        expected_formula_versions=dict(report.formula_versions),
        reference_measurement=ReferenceMeasurement(
            environment="unit test",
            measured_at="2026-07-16T00:00:00+00:00",
            total_p95_ms=1,
            slowest_node_p95_ms=0.1,
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
