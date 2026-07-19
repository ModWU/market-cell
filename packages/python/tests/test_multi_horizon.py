from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from market_cell.engine import AnalysisEngine
from market_cell.graph import liquidity_analysis_graph
from market_cell.horizons import (
    MultiHorizonAnalyzer,
    MultiHorizonExecutionError,
    MultiHorizonRequest,
    validate_multi_horizon_request,
)
from market_cell.inputs import InputCompositionError
from market_cell.models import AnalysisRequest
from market_cell.policies import DecisionPolicy
from market_cell.registry import default_registry
from market_cell.replay import ReplayRunner
from market_cell.reports import FileSystemReportStore
from market_cell.validation import ValidationError


ROOT = Path(__file__).resolve().parents[3]
VECTOR_PATH = (
    ROOT
    / "contracts"
    / "test_vectors"
    / "multi_horizon_request_v1.json"
)


class MultiHorizonRequestTests(unittest.TestCase):
    def test_shared_identity_vector_is_stable_and_metadata_independent(self):
        vector = _vector()
        request = MultiHorizonRequest.from_dict(vector["request"])

        validate_multi_horizon_request(request)

        self.assertEqual(request.content_hash, vector["expected_content_hash"])
        self.assertEqual(
            request.payload_size_bytes,
            vector["expected_payload_size_bytes"],
        )
        self.assertEqual(request.request_id, vector["expected_request_id"])
        self.assertEqual(request.horizon_order, ["15m", "1h"])
        self.assertEqual(
            replace(request, metadata={"different": True}).content_hash,
            request.content_hash,
        )
        self.assertNotEqual(
            replace(
                request,
                requests=list(reversed(request.requests)),
            ).content_hash,
            request.content_hash,
        )

    def test_validation_rejects_invalid_count_scope_and_horizon_order(self):
        request = _request()

        with self.assertRaisesRegex(ValidationError, "requests 数量"):
            validate_multi_horizon_request(
                replace(request, requests=request.requests[:1])
            )
        with self.assertRaisesRegex(ValidationError, "target 完全一致"):
            validate_multi_horizon_request(
                replace(
                    request,
                    requests=[
                        request.requests[0],
                        replace(request.requests[1], target="ETH/USD"),
                    ],
                )
            )
        with self.assertRaisesRegex(ValidationError, "从短到长"):
            validate_multi_horizon_request(
                replace(request, requests=list(reversed(request.requests)))
            )
        with self.assertRaisesRegex(ValidationError, "horizon 不能重复"):
            validate_multi_horizon_request(
                replace(
                    request,
                    requests=[
                        request.requests[0],
                        replace(request.requests[1], horizon="15m"),
                    ],
                )
            )
        with self.assertRaisesRegex(ValidationError, "等价周期"):
            validate_multi_horizon_request(
                replace(
                    request,
                    requests=[
                        replace(request.requests[0], horizon="60m"),
                        request.requests[1],
                    ],
                )
            )
        with self.assertRaisesRegex(ValidationError, "正整数"):
            validate_multi_horizon_request(
                replace(
                    request,
                    requests=[
                        replace(request.requests[0], horizon="015m"),
                        request.requests[1],
                    ],
                )
            )

    def test_validation_rejects_unaligned_or_unordered_candle_boundaries(self):
        request = _request()
        short = request.requests[0]
        latest = short.candles[-1]

        with self.assertRaisesRegex(ValidationError, "不能晚于 as_of_ms"):
            validate_multi_horizon_request(
                replace(
                    request,
                    requests=[
                        replace(
                            short,
                            candles=[
                                *short.candles[:-1],
                                replace(
                                    latest,
                                    timestamp=str(request.as_of_ms + 1),
                                ),
                            ],
                        ),
                        request.requests[1],
                    ],
                )
            )
        with self.assertRaisesRegex(ValidationError, "超过一个周期"):
            validate_multi_horizon_request(
                replace(
                    request,
                    requests=[
                        replace(
                            short,
                            candles=[
                                replace(
                                    short.candles[0],
                                    timestamp=str(request.as_of_ms - 1_800_001),
                                ),
                                replace(
                                    latest,
                                    timestamp=str(request.as_of_ms - 900_001),
                                ),
                            ],
                        ),
                        request.requests[1],
                    ],
                )
            )
        with self.assertRaisesRegex(ValidationError, "严格升序"):
            validate_multi_horizon_request(
                replace(
                    request,
                    requests=[
                        replace(short, candles=list(reversed(short.candles))),
                        request.requests[1],
                    ],
                )
            )
        with self.assertRaisesRegex(ValidationError, "可解析时间"):
            validate_multi_horizon_request(
                replace(
                    request,
                    requests=[
                        replace(
                            short,
                            candles=[
                                *short.candles[:-1],
                                replace(latest, timestamp="not-a-time"),
                            ],
                        ),
                        request.requests[1],
                    ],
                )
            )


class MultiHorizonAnalyzerTests(unittest.TestCase):
    def test_analyzer_preserves_order_and_refuses_premature_aggregation(self):
        request = _request()

        analysis = MultiHorizonAnalyzer().run(request)

        self.assertEqual(analysis.target, request.target)
        self.assertEqual(analysis.as_of_ms, request.as_of_ms)
        self.assertEqual(analysis.horizon_order, ["15m", "1h"])
        self.assertEqual(
            [report.horizon for report in analysis.reports],
            analysis.horizon_order,
        )
        self.assertEqual(analysis.aggregation_status, "not_computed")
        self.assertNotIn("direction", analysis.to_dict())
        self.assertTrue(
            all(
                report.formula_versions == analysis.formula_versions
                for report in analysis.reports
            )
        )
        self.assertEqual(analysis.metadata["failure_mode"], "fail_fast")

        with self.assertRaisesRegex(ValueError, "report order"):
            replace(analysis, reports=list(reversed(analysis.reports)))
        with self.assertRaisesRegex(ValueError, "request_id"):
            replace(analysis, request_id="multi-horizon-request:bad")
        with self.assertRaisesRegex(ValueError, "decision scope"):
            first = analysis.reports[0]
            replace(
                analysis,
                reports=[
                    replace(
                        first,
                        decision=replace(first.decision, horizon="4h"),
                    ),
                    *analysis.reports[1:],
                ],
            )

    def test_child_runs_keep_batch_audit_and_replay_independently(self):
        request = _request()

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))
            analysis = MultiHorizonAnalyzer(
                engine_factory=lambda _: AnalysisEngine(report_store=store)
            ).run(request, metadata={"caller": "unit-test"})
            runs = [
                store.load_run(report.run_id or "")
                for report in analysis.reports
            ]
            comparisons = [
                ReplayRunner(store).replay(report.report_id or "")
                for report in analysis.reports
            ]

        for index, run in enumerate(runs):
            audit = run["metadata"]["multi_horizon"]
            self.assertEqual(audit["batch_id"], analysis.batch_id)
            self.assertEqual(audit["request_id"], request.request_id)
            self.assertEqual(audit["request_hash"], request.content_hash)
            self.assertEqual(audit["horizon_index"], index)
            self.assertEqual(audit["horizon_order"], ["15m", "1h"])
            self.assertEqual(
                audit["request_metadata"],
                request.metadata,
            )
            self.assertEqual(run["metadata"]["caller"], "unit-test")
        self.assertTrue(
            all(comparison.result_stable for comparison in comparisons)
        )

    def test_preflight_rejects_graph_drift_before_any_horizon_runs(self):
        request = _request()

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))

            def factory(child: AnalysisRequest) -> AnalysisEngine:
                graph = (
                    liquidity_analysis_graph()
                    if child.horizon == "1h"
                    else None
                )
                return AnalysisEngine(
                    graph_definition=graph,
                    report_store=store,
                )

            with self.assertRaises(MultiHorizonExecutionError) as context:
                MultiHorizonAnalyzer(factory).run(request)

            self.assertEqual(context.exception.code, "graph_mismatch")
            self.assertEqual(context.exception.failed_horizon, "1h")
            self.assertEqual(context.exception.completed_reports, ())
            self.assertEqual(store.list_reports(), [])

    def test_preflight_rejects_formula_drift_before_execution(self):
        request = _request()

        def factory(child: AnalysisRequest) -> AnalysisEngine:
            if child.horizon == "1h":
                policy = DecisionPolicy(
                    formula_version="decision_weighted_score_test_drift"
                )
                return AnalysisEngine(
                    registry=default_registry(decision_policy=policy)
                )
            return AnalysisEngine()

        with self.assertRaises(MultiHorizonExecutionError) as context:
            MultiHorizonAnalyzer(factory).run(request)

        self.assertEqual(context.exception.code, "formula_version_mismatch")
        self.assertEqual(context.exception.completed_reports, ())

    def test_fail_fast_error_preserves_completed_horizon_boundary(self):
        request = _request()

        class FailingEngine(AnalysisEngine):
            def run(self, *args, **kwargs):
                raise RuntimeError("planned horizon failure")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemReportStore(Path(temp_dir))

            def factory(child: AnalysisRequest) -> AnalysisEngine:
                if child.horizon == "1h":
                    return FailingEngine(report_store=store)
                return AnalysisEngine(report_store=store)

            with self.assertRaises(MultiHorizonExecutionError) as context:
                MultiHorizonAnalyzer(factory).run(request)

            error = context.exception
            stored_reports = store.list_reports()

        self.assertEqual(error.code, "analysis_failure")
        self.assertEqual(error.failed_horizon, "1h")
        self.assertEqual(
            [report.horizon for report in error.completed_reports],
            ["15m"],
        )
        self.assertEqual(len(stored_reports), 1)
        self.assertEqual(error.to_dict()["completed_horizons"], ["15m"])
        self.assertEqual(error.to_dict()["request_hash"], request.content_hash)
        self.assertEqual(error.to_dict()["as_of_ms"], request.as_of_ms)

    def test_post_run_scope_and_formula_drift_fail_closed(self):
        request = _request()

        class ScopeDriftEngine(AnalysisEngine):
            def run(self, *args, **kwargs):
                report = super().run(*args, **kwargs)
                return replace(
                    report,
                    decision=replace(report.decision, horizon="4h"),
                )

        class FormulaDriftEngine(AnalysisEngine):
            def run(self, *args, **kwargs):
                report = super().run(*args, **kwargs)
                return replace(
                    report,
                    formula_versions={
                        **report.formula_versions,
                        "root.decision": "drifted-after-preflight",
                    },
                )

        for engine_type, expected_code in (
            (ScopeDriftEngine, "report_scope_mismatch"),
            (FormulaDriftEngine, "report_formula_mismatch"),
        ):
            with self.subTest(expected_code=expected_code):

                def factory(child: AnalysisRequest) -> AnalysisEngine:
                    if child.horizon == "1h":
                        return engine_type()
                    return AnalysisEngine()

                with self.assertRaises(MultiHorizonExecutionError) as context:
                    MultiHorizonAnalyzer(factory).run(request)

                self.assertEqual(context.exception.code, expected_code)
                self.assertEqual(
                    [
                        report.horizon
                        for report in context.exception.completed_reports
                    ],
                    ["15m"],
                )

    def test_extra_inputs_must_reference_declared_horizons(self):
        with self.assertRaisesRegex(InputCompositionError, "unknown horizons"):
            MultiHorizonAnalyzer().run(
                _request(),
                input_snapshots_by_horizon={"4h": []},
            )

    def test_reserved_batch_metadata_cannot_be_overwritten(self):
        with self.assertRaisesRegex(ValueError, "reserved"):
            MultiHorizonAnalyzer().run(
                _request(),
                metadata={"multi_horizon": {"batch_id": "tampered"}},
            )


def _vector() -> dict:
    return json.loads(VECTOR_PATH.read_text(encoding="utf-8"))


def _request() -> MultiHorizonRequest:
    return MultiHorizonRequest.from_dict(_vector()["request"])


if __name__ == "__main__":
    unittest.main()
