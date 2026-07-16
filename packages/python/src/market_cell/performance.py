from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
import json
import platform
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from market_cell.engine import AnalysisEngine
from market_cell.events import EventBus, utc_now_iso
from market_cell.inputs import InputSnapshot
from market_cell.models import AnalysisReport, AnalysisRequest


PERFORMANCE_BASELINE_SCHEMA_VERSION = "performance_baseline.v1"
PERFORMANCE_BENCHMARK_RESULT_SCHEMA_VERSION = "performance_benchmark_result.v1"


class PerformanceBaselineError(ValueError):
    pass


@dataclass(frozen=True)
class PerformanceThresholds:
    total_p95_ms: float
    node_p95_ms: float
    rationale: str


@dataclass(frozen=True)
class ExpectedDecision:
    cell_id: str
    direction: str
    score: float
    risk_level: str | None
    action_posture: str | None
    child_count: int


@dataclass(frozen=True)
class ReferenceMeasurement:
    environment: str
    measured_at: str
    total_p95_ms: float
    slowest_node_p95_ms: float


@dataclass(frozen=True)
class PerformanceBaseline:
    benchmark_id: str
    input_file: str
    input_hash: str
    warmup_runs: int
    measured_runs: int
    expected_node_count: int
    thresholds: PerformanceThresholds
    expected_decision: ExpectedDecision
    expected_formula_versions: dict[str, str]
    reference_measurement: ReferenceMeasurement
    schema_version: str = PERFORMANCE_BASELINE_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PerformanceBaseline":
        baseline = cls(
            benchmark_id=str(data["benchmark_id"]),
            input_file=str(data["input_file"]),
            input_hash=str(data["input_hash"]),
            warmup_runs=int(data["warmup_runs"]),
            measured_runs=int(data["measured_runs"]),
            expected_node_count=int(data["expected_node_count"]),
            thresholds=PerformanceThresholds(**data["thresholds"]),
            expected_decision=ExpectedDecision(**data["expected_decision"]),
            expected_formula_versions={
                str(key): str(value)
                for key, value in data["expected_formula_versions"].items()
            },
            reference_measurement=ReferenceMeasurement(
                **data["reference_measurement"]
            ),
            schema_version=str(data.get("schema_version", "")),
        )
        baseline.validate()
        return baseline

    @classmethod
    def load(cls, path: Path | str) -> "PerformanceBaseline":
        return cls.from_dict(
            json.loads(Path(path).read_text(encoding="utf-8"))
        )

    def validate(self) -> None:
        issues: list[str] = []
        if self.schema_version != PERFORMANCE_BASELINE_SCHEMA_VERSION:
            issues.append(
                f"schema_version must be {PERFORMANCE_BASELINE_SCHEMA_VERSION}"
            )
        if not self.benchmark_id.strip():
            issues.append("benchmark_id must not be empty")
        if not self.input_file.strip():
            issues.append("input_file must not be empty")
        if len(self.input_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.input_hash
        ):
            issues.append("input_hash must be a SHA-256 hex digest")
        if self.warmup_runs < 0:
            issues.append("warmup_runs must not be negative")
        if self.measured_runs < 5:
            issues.append("measured_runs must be at least 5")
        if self.expected_node_count < 1:
            issues.append("expected_node_count must be at least 1")
        if self.thresholds.total_p95_ms <= 0:
            issues.append("total_p95_ms must be positive")
        if self.thresholds.node_p95_ms <= 0:
            issues.append("node_p95_ms must be positive")
        if not self.thresholds.rationale.strip():
            issues.append("threshold rationale must not be empty")
        if self.expected_decision.child_count < 0:
            issues.append("expected child_count must not be negative")
        if not self.expected_formula_versions:
            issues.append("expected_formula_versions must not be empty")
        if issues:
            raise PerformanceBaselineError("; ".join(issues))

    def resolve_input_path(self, baseline_path: Path | str) -> Path:
        path = Path(self.input_file)
        if path.is_absolute():
            return path
        return Path(baseline_path).resolve().parent / path


@dataclass(frozen=True)
class DurationDistribution:
    sample_count: int
    average_ms: float
    min_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NodePerformance:
    node_id: str
    cell_id: str
    durations: DurationDistribution

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "cell_id": self.cell_id,
            "durations": self.durations.to_dict(),
        }


@dataclass(frozen=True)
class BenchmarkFailure:
    code: str
    message: str
    actual: Any
    expected: Any

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PerformanceBenchmarkResult:
    benchmark_id: str
    baseline_schema_version: str
    input_hash: str
    warmup_runs: int
    measured_runs: int
    expected_node_count: int
    thresholds: PerformanceThresholds
    reference_measurement: ReferenceMeasurement
    total_durations: DurationDistribution
    nodes: list[NodePerformance]
    slowest_node_id: str | None
    actual_decision: dict[str, Any]
    actual_formula_versions: dict[str, str]
    correctness_failures: list[BenchmarkFailure]
    performance_failures: list[BenchmarkFailure]
    environment: dict[str, str]
    created_at: str
    schema_version: str = PERFORMANCE_BENCHMARK_RESULT_SCHEMA_VERSION

    @property
    def passed(self) -> bool:
        return not self.correctness_failures and not self.performance_failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "baseline_schema_version": self.baseline_schema_version,
            "input_hash": self.input_hash,
            "warmup_runs": self.warmup_runs,
            "measured_runs": self.measured_runs,
            "expected_node_count": self.expected_node_count,
            "thresholds": asdict(self.thresholds),
            "reference_measurement": asdict(self.reference_measurement),
            "total_durations": self.total_durations.to_dict(),
            "nodes": [node.to_dict() for node in self.nodes],
            "slowest_node_id": self.slowest_node_id,
            "actual_decision": dict(self.actual_decision),
            "actual_formula_versions": dict(self.actual_formula_versions),
            "correctness_failures": [
                failure.to_dict() for failure in self.correctness_failures
            ],
            "performance_failures": [
                failure.to_dict() for failure in self.performance_failures
            ],
            "environment": dict(self.environment),
            "created_at": self.created_at,
            "passed": self.passed,
            "schema_version": self.schema_version,
        }


EngineFactory = Callable[[EventBus], AnalysisEngine]


def run_performance_benchmark(
    baseline_path: Path | str,
    *,
    engine_factory: EngineFactory | None = None,
) -> PerformanceBenchmarkResult:
    baseline_path = Path(baseline_path)
    baseline = PerformanceBaseline.load(baseline_path)
    request = AnalysisRequest.from_dict(
        json.loads(
            baseline.resolve_input_path(baseline_path).read_text(encoding="utf-8")
        )
    )
    input_hash = InputSnapshot.from_analysis_request(request).content_hash
    event_bus = EventBus()
    engine = (
        engine_factory(event_bus)
        if engine_factory is not None
        else AnalysisEngine(event_bus=event_bus)
    )

    for _ in range(baseline.warmup_runs):
        engine.run(request)
        event_bus.events.clear()

    total_durations: list[float] = []
    node_durations: dict[tuple[str, str], list[float]] = defaultdict(list)
    reports: list[AnalysisReport] = []
    for _ in range(baseline.measured_runs):
        event_bus.events.clear()
        started = perf_counter()
        report = engine.run(request)
        total_durations.append((perf_counter() - started) * 1000)
        reports.append(report)
        for event in event_bus.events:
            if event.name != "cell.completed":
                continue
            duration_ms = event.payload.get("duration_ms")
            if duration_ms is None:
                continue
            node_durations[
                (str(event.payload["node_id"]), str(event.payload["cell_id"]))
            ].append(float(duration_ms))

    return evaluate_performance_benchmark(
        baseline,
        input_hash=input_hash,
        total_duration_samples=total_durations,
        node_duration_samples=node_durations,
        reports=reports,
    )


def evaluate_performance_benchmark(
    baseline: PerformanceBaseline,
    *,
    input_hash: str,
    total_duration_samples: list[float],
    node_duration_samples: dict[tuple[str, str], list[float]],
    reports: list[AnalysisReport],
) -> PerformanceBenchmarkResult:
    if not reports:
        raise PerformanceBaselineError("benchmark requires at least one report")
    total_distribution = _duration_distribution(total_duration_samples)
    nodes = sorted(
        (
            NodePerformance(
                node_id=node_id,
                cell_id=cell_id,
                durations=_duration_distribution(samples),
            )
            for (node_id, cell_id), samples in node_duration_samples.items()
        ),
        key=lambda node: node.node_id,
    )
    slowest_node = max(
        nodes,
        key=lambda node: (node.durations.p95_ms, node.node_id),
        default=None,
    )
    actual_decision = _decision_signature(reports[-1])
    actual_formula_versions = dict(reports[-1].formula_versions)
    correctness_failures = _correctness_failures(
        baseline,
        input_hash=input_hash,
        nodes=nodes,
        reports=reports,
        actual_decision=actual_decision,
        actual_formula_versions=actual_formula_versions,
    )
    performance_failures = _performance_failures(
        baseline,
        total_distribution=total_distribution,
        slowest_node=slowest_node,
    )
    return PerformanceBenchmarkResult(
        benchmark_id=baseline.benchmark_id,
        baseline_schema_version=baseline.schema_version,
        input_hash=input_hash,
        warmup_runs=baseline.warmup_runs,
        measured_runs=baseline.measured_runs,
        expected_node_count=baseline.expected_node_count,
        thresholds=baseline.thresholds,
        reference_measurement=baseline.reference_measurement,
        total_durations=total_distribution,
        nodes=nodes,
        slowest_node_id=slowest_node.node_id if slowest_node is not None else None,
        actual_decision=actual_decision,
        actual_formula_versions=actual_formula_versions,
        correctness_failures=correctness_failures,
        performance_failures=performance_failures,
        environment={
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        created_at=utc_now_iso(),
    )


def _correctness_failures(
    baseline: PerformanceBaseline,
    *,
    input_hash: str,
    nodes: list[NodePerformance],
    reports: list[AnalysisReport],
    actual_decision: dict[str, Any],
    actual_formula_versions: dict[str, str],
) -> list[BenchmarkFailure]:
    failures: list[BenchmarkFailure] = []
    _append_mismatch(
        failures,
        "input_hash_mismatch",
        "benchmark input does not match the versioned baseline",
        input_hash,
        baseline.input_hash,
    )
    expected_decision = asdict(baseline.expected_decision)
    for field_name, expected in expected_decision.items():
        actual = actual_decision[field_name]
        if field_name == "score":
            if abs(float(actual) - float(expected)) > 1e-6:
                _append_mismatch(
                    failures,
                    "decision_mismatch",
                    f"decision {field_name} changed",
                    actual,
                    expected,
                )
        elif actual != expected:
            _append_mismatch(
                failures,
                "decision_mismatch",
                f"decision {field_name} changed",
                actual,
                expected,
            )
    if actual_formula_versions != baseline.expected_formula_versions:
        _append_mismatch(
            failures,
            "formula_versions_mismatch",
            "formula versions changed from the benchmark baseline",
            actual_formula_versions,
            baseline.expected_formula_versions,
        )
    signatures = {_report_signature(report) for report in reports}
    if len(signatures) != 1:
        _append_mismatch(
            failures,
            "nondeterministic_results",
            "measured runs produced different analysis results",
            len(signatures),
            1,
        )
    incomplete_nodes = [
        node.node_id
        for node in nodes
        if node.durations.sample_count != baseline.measured_runs
    ]
    if incomplete_nodes:
        _append_mismatch(
            failures,
            "incomplete_node_samples",
            "some nodes did not produce one duration sample per measured run",
            incomplete_nodes,
            baseline.measured_runs,
        )
    if len(nodes) != baseline.expected_node_count:
        _append_mismatch(
            failures,
            "node_count_mismatch",
            "observed node count changed from the benchmark baseline",
            len(nodes),
            baseline.expected_node_count,
        )
    if not nodes:
        _append_mismatch(
            failures,
            "missing_node_samples",
            "benchmark did not observe any completed Cell node",
            0,
            "> 0",
        )
    return failures


def _performance_failures(
    baseline: PerformanceBaseline,
    *,
    total_distribution: DurationDistribution,
    slowest_node: NodePerformance | None,
) -> list[BenchmarkFailure]:
    failures: list[BenchmarkFailure] = []
    if total_distribution.p95_ms > baseline.thresholds.total_p95_ms:
        _append_mismatch(
            failures,
            "total_p95_regression",
            "total analysis P95 exceeded the baseline threshold",
            total_distribution.p95_ms,
            baseline.thresholds.total_p95_ms,
        )
    if (
        slowest_node is not None
        and slowest_node.durations.p95_ms > baseline.thresholds.node_p95_ms
    ):
        _append_mismatch(
            failures,
            "node_p95_regression",
            f"node {slowest_node.node_id} P95 exceeded the baseline threshold",
            slowest_node.durations.p95_ms,
            baseline.thresholds.node_p95_ms,
        )
    return failures


def _duration_distribution(samples: list[float]) -> DurationDistribution:
    if not samples:
        raise PerformanceBaselineError("duration samples must not be empty")
    values = sorted(max(float(value), 0.0) for value in samples)
    return DurationDistribution(
        sample_count=len(values),
        average_ms=round(sum(values) / len(values), 6),
        min_ms=round(values[0], 6),
        p50_ms=round(_percentile(values, 0.50), 6),
        p95_ms=round(_percentile(values, 0.95), 6),
        p99_ms=round(_percentile(values, 0.99), 6),
        max_ms=round(values[-1], 6),
    )


def _percentile(values: list[float], percentile: float) -> float:
    index = min(max(int(round((len(values) - 1) * percentile)), 0), len(values) - 1)
    return values[index]


def _decision_signature(report: AnalysisReport) -> dict[str, Any]:
    decision = report.decision
    return {
        "cell_id": decision.cell_id,
        "direction": decision.direction,
        "score": decision.score,
        "risk_level": decision.risk_level,
        "action_posture": decision.action_posture,
        "child_count": len(decision.children),
    }


def _report_signature(report: AnalysisReport) -> str:
    payload = {
        "decision": report.decision.to_dict(),
        "formula_versions": report.formula_versions,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _append_mismatch(
    failures: list[BenchmarkFailure],
    code: str,
    message: str,
    actual: Any,
    expected: Any,
) -> None:
    if actual == expected:
        return
    failures.append(
        BenchmarkFailure(
            code=code,
            message=message,
            actual=actual,
            expected=expected,
        )
    )
