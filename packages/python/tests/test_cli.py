from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_cell.cli import main
from market_cell.reports import FileSystemReportStore


ROOT = Path(__file__).resolve().parents[3]


class BenchmarkCliTests(unittest.TestCase):
    def test_benchmark_returns_zero_when_all_checks_pass(self):
        code, payload = _run(_Result())

        self.assertEqual(code, 0)
        self.assertTrue(payload["passed"])

    def test_benchmark_returns_two_for_correctness_drift(self):
        code, _ = _run(_Result(correctness_failures=[{"code": "drift"}]))

        self.assertEqual(code, 2)

    def test_benchmark_returns_three_for_performance_regression(self):
        code, _ = _run(_Result(performance_failures=[{"code": "slow"}]))

        self.assertEqual(code, 3)


class MultiHorizonCliTests(unittest.TestCase):
    def test_analyze_multi_outputs_unaggregated_horizon_reports(self):
        output = StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "analyze-multi",
                    str(ROOT / "examples" / "btc_usd_multi_horizon_sample.json"),
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema_version"], "multi_horizon_analysis.v1")
        self.assertEqual(payload["horizon_order"], ["15m", "1h", "4h"])
        self.assertEqual(payload["aggregation_status"], "not_computed")
        self.assertNotIn("direction", payload)

    def test_analyze_multi_decide_outputs_versioned_horizon_decision(self):
        output = StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "analyze-multi",
                    str(
                        ROOT
                        / "examples"
                        / "btc_usd_multi_horizon_sample.json"
                    ),
                    "--decide",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema_version"], "horizon_decision.v1")
        self.assertEqual(
            payload["formula_version"],
            "horizon_structure_alignment_v0.1",
        )
        self.assertEqual(payload["horizon_order"], ["15m", "1h", "4h"])
        self.assertEqual(
            [item["horizon"] for item in payload["source_signals"]],
            payload["horizon_order"],
        )
        self.assertIn(
            payload["alignment_status"],
            {"aligned", "partial", "conflicted", "indeterminate"},
        )
        self.assertEqual(
            [item["band"] for item in payload["band_decisions"]],
            ["short", "medium"],
        )

    def test_analyze_multi_save_persists_each_child_report(self):
        output = StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            with redirect_stdout(output):
                code = main(
                    [
                        "analyze-multi",
                        str(
                            ROOT
                            / "examples"
                            / "btc_usd_multi_horizon_sample.json"
                        ),
                        "--save",
                        "--report-dir",
                        temp_dir,
                    ]
                )
            report_ids = FileSystemReportStore(temp_dir).list_reports()

        self.assertEqual(code, 0)
        self.assertEqual(len(report_ids), 3)


class _Result:
    def __init__(
        self,
        *,
        correctness_failures=None,
        performance_failures=None,
    ) -> None:
        self.correctness_failures = correctness_failures or []
        self.performance_failures = performance_failures or []

    def to_dict(self):
        return {
            "correctness_failures": self.correctness_failures,
            "performance_failures": self.performance_failures,
            "passed": not self.correctness_failures and not self.performance_failures,
        }


def _run(result):
    output = StringIO()
    with patch("market_cell.cli.run_performance_benchmark", return_value=result):
        with redirect_stdout(output):
            code = main(["benchmark", "baseline.json"])
    return code, json.loads(output.getvalue())


if __name__ == "__main__":
    unittest.main()
