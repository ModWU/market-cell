from contextlib import redirect_stdout
from io import StringIO
import json
import unittest
from unittest.mock import patch

from market_cell.cli import main


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
