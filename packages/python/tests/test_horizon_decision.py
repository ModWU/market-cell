from dataclasses import replace
import json
import math
from pathlib import Path
import unittest

from market_cell.horizons import (
    HorizonDecisionCell,
    HorizonDecisionPolicy,
    MultiHorizonAnalysis,
)
from market_cell.models import AnalysisReport, CellResult
from market_cell.registry import CellNotRegisteredError, default_registry


ROOT = Path(__file__).resolve().parents[3]
VALIDATION_PATH = (
    ROOT / "validation" / "cells" / "horizon_decision_v0.1.json"
)
VECTOR_PATH = (
    ROOT / "contracts" / "test_vectors" / "horizon_decision_v1.json"
)
SOURCE_FORMULA_VERSIONS = {
    "root.decision": "decision_weighted_score_v0.5",
}


class HorizonDecisionCellTests(unittest.TestCase):
    def test_versioned_validation_cases_cover_alignment_conflict_and_risk(self):
        fixture = _fixture()
        cell = HorizonDecisionCell()

        self.assertEqual(
            fixture["schema_version"],
            "horizon_decision_validation_fixture.v1",
        )
        self.assertEqual(fixture["cell_id"], cell.cell_id)
        self.assertEqual(fixture["formula_version"], cell.formula_version)
        self.assertTrue(fixture["known_limitations"])
        false_positive_cases = [
            case
            for case in fixture["cases"]
            if case["case_type"] == "known_false_positive_guard"
        ]
        self.assertGreaterEqual(len(false_positive_cases), 3)
        self.assertTrue(
            all(case.get("false_positive_note") for case in false_positive_cases)
        )

        for case in fixture["cases"]:
            with self.subTest(case_id=case["case_id"]):
                analysis = _analysis(case["signals"])
                decision = cell.analyze(analysis)
                expected = case["expected"]

                self.assertEqual(
                    decision.identity_payload(),
                    cell.identity_payload(analysis),
                )

                for field_name in (
                    "direction",
                    "structural_direction",
                    "alignment_status",
                    "conflict_type",
                    "risk_level",
                    "action_posture",
                ):
                    self.assertEqual(
                        getattr(decision, field_name),
                        expected[field_name],
                    )
                self.assertEqual(
                    len(decision.evidence),
                    len(case["signals"]),
                )
                self.assertEqual(
                    [item.horizon for item in decision.source_signals],
                    decision.horizon_order,
                )
                self.assertAlmostEqual(
                    sum(item.weight for item in decision.evidence),
                    1,
                    places=6,
                )
                if decision.alignment_status == "conflicted":
                    self.assertGreater(decision.conflict_score, 0)
                    self.assertIn("冲突", decision.explanation)
                else:
                    self.assertEqual(decision.conflict_score, 0)

    def test_band_boundaries_are_explicit_and_longer_horizons_hold_authority(self):
        policy = HorizonDecisionPolicy()

        self.assertEqual(policy.band_for("15m"), "short")
        self.assertEqual(policy.band_for("1h"), "short")
        self.assertEqual(policy.band_for("4h"), "medium")
        self.assertEqual(policy.band_for("1d"), "medium")
        self.assertEqual(policy.band_for("1w"), "long")
        self.assertEqual(policy.band_for("1M"), "long")

        signals = _fixture()["cases"][0]["signals"]
        decision = HorizonDecisionCell().analyze(_analysis(signals))
        weights = {
            item.source.removeprefix("horizon:"): item.weight
            for item in decision.evidence
        }

        self.assertGreater(weights["1w"], weights["4h"])
        self.assertGreater(weights["4h"], weights["15m"])

    def test_eight_horizon_boundary_preserves_band_partition_and_weights(self):
        horizons = ["1m", "5m", "15m", "1h", "4h", "1d", "1w", "1M"]
        signals = [
            {
                "horizon": horizon,
                "direction": "bullish",
                "score": 20 + index,
                "strength": 40 + index,
                "confidence": 70 + index,
                "volatility_risk": 20 + index,
                "manipulation_risk": 10 + index,
            }
            for index, horizon in enumerate(horizons)
        ]

        decision = HorizonDecisionCell().analyze(_analysis(signals))

        self.assertEqual(decision.horizon_order, horizons)
        self.assertEqual(decision.alignment_status, "aligned")
        self.assertEqual(
            [item.horizons for item in decision.band_decisions],
            [
                ["1m", "5m", "15m", "1h"],
                ["4h", "1d"],
                ["1w", "1M"],
            ],
        )
        self.assertEqual(
            [item.anchor_horizon for item in decision.band_decisions],
            ["1h", "1d", "1M"],
        )
        self.assertAlmostEqual(
            sum(item.weight for item in decision.evidence),
            1,
            places=6,
        )

    def test_shared_decision_identity_vector_is_stable(self):
        vector = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
        signals = _fixture()["cases"][0]["signals"]
        analysis = _analysis(signals)
        cell = HorizonDecisionCell()

        payload = cell.identity_payload(analysis)
        decision = cell.analyze(analysis)

        self.assertEqual(payload, vector["identity_payload"])
        self.assertEqual(decision.identity_payload(), payload)
        self.assertEqual(
            decision.decision_hash,
            vector["expected_decision_hash"],
        )
        self.assertEqual(
            decision.decision_id,
            vector["expected_decision_id"],
        )

    def test_decision_identity_excludes_run_metadata_but_covers_used_signals(self):
        signals = _fixture()["cases"][0]["signals"]
        analysis = _analysis(signals)
        cell = HorizonDecisionCell()

        first = cell.analyze(analysis)
        changed_batch = replace(
            analysis,
            batch_id="multi-horizon:" + "d" * 32,
            created_at="2026-07-19T01:00:00+00:00",
            metadata={"caller": "different"},
            reports=[
                replace(
                    report,
                    run_id=f"other-{index}",
                    report_id=f"other-{index}",
                    created_at="2026-07-19T01:00:00+00:00",
                )
                for index, report in enumerate(analysis.reports)
            ],
        )
        second = cell.analyze(changed_batch)

        changed_report = analysis.reports[0]
        changed_signal = replace(
            analysis,
            reports=[
                replace(
                    changed_report,
                    decision=replace(
                        changed_report.decision,
                        score=changed_report.decision.score + 1,
                    ),
                ),
                *analysis.reports[1:],
            ],
        )
        third = cell.analyze(changed_signal)

        self.assertEqual(first.decision_hash, second.decision_hash)
        self.assertEqual(first.decision_id, second.decision_id)
        self.assertNotEqual(first.decision_hash, third.decision_hash)

    def test_policy_configuration_is_part_of_decision_identity(self):
        analysis = _analysis(_fixture()["cases"][0]["signals"])

        baseline = HorizonDecisionCell().analyze(analysis)
        stricter = HorizonDecisionCell(
            HorizonDecisionPolicy(minimum_direction_confidence=55)
        ).analyze(analysis)

        self.assertNotEqual(baseline.decision_hash, stricter.decision_hash)

    def test_policy_rejects_non_finite_or_invalid_authority_configuration(self):
        with self.assertRaisesRegex(ValueError, "weights"):
            HorizonDecisionPolicy(
                band_authority={
                    "short": 0.2,
                    "medium": 0.3,
                    "long": math.inf,
                }
            )
        with self.assertRaisesRegex(ValueError, "thresholds"):
            HorizonDecisionPolicy(minimum_direction_confidence=math.nan)
        with self.assertRaisesRegex(ValueError, "boundaries"):
            HorizonDecisionPolicy(
                short_band_max_ms=604_800_000,
                long_band_min_ms=14_400_000,
            )

    def test_decision_identity_normalizes_equivalent_numeric_types(self):
        analysis = _analysis(_fixture()["cases"][0]["signals"])
        first = analysis.reports[0]
        decision = first.decision
        integer_backed = replace(
            analysis,
            reports=[
                replace(
                    first,
                    decision=replace(
                        decision,
                        score=int(decision.score),
                        strength=int(decision.strength),
                        confidence=int(decision.confidence),
                        volatility_risk=int(decision.volatility_risk),
                        manipulation_risk=int(decision.manipulation_risk),
                    ),
                ),
                *analysis.reports[1:],
            ],
        )

        cell = HorizonDecisionCell()

        self.assertEqual(
            cell.analyze(analysis).decision_hash,
            cell.analyze(integer_backed).decision_hash,
        )

    def test_output_model_rejects_identity_and_partition_tampering(self):
        decision = HorizonDecisionCell().analyze(
            _analysis(_fixture()["cases"][0]["signals"])
        )

        with self.assertRaisesRegex(ValueError, "id must match"):
            replace(decision, decision_id="horizon-decision:" + "0" * 24)
        with self.assertRaisesRegex(ValueError, "partition"):
            replace(
                decision,
                band_decisions=decision.band_decisions[:-1],
            )
        with self.assertRaisesRegex(ValueError, "source signals"):
            replace(
                decision,
                source_signals=list(reversed(decision.source_signals)),
            )
        with self.assertRaisesRegex(ValueError, "canonical payload"):
            replace(
                decision,
                structural_score=decision.structural_score + 1,
            )
        with self.assertRaisesRegex(ValueError, "canonical payload"):
            replace(
                decision,
                policy={
                    **decision.policy,
                    "minimum_direction_confidence": 50.0,
                },
            )

    def test_invalid_source_numbers_fail_closed(self):
        analysis = _analysis(_fixture()["cases"][0]["signals"])
        first = analysis.reports[0]
        invalid = replace(
            analysis,
            reports=[
                replace(
                    first,
                    decision=replace(first.decision, confidence=math.nan),
                ),
                *analysis.reports[1:],
            ],
        )

        with self.assertRaisesRegex(ValueError, "finite"):
            HorizonDecisionCell().analyze(invalid)

    def test_application_level_cell_is_not_registered_in_single_horizon_dag(self):
        cell = HorizonDecisionCell()

        self.assertEqual(cell.input_schema_versions, ["multi_horizon_analysis.v1"])
        self.assertEqual(cell.output_schema_version, "horizon_decision.v1")
        self.assertEqual(cell.status, "experimental")
        with self.assertRaises(CellNotRegisteredError):
            default_registry().resolve(cell.cell_id)


def _fixture() -> dict:
    return json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))


def _analysis(signals: list[dict]) -> MultiHorizonAnalysis:
    reports = [_report(index, item) for index, item in enumerate(signals)]
    request_hash = "a" * 64
    return MultiHorizonAnalysis(
        batch_id="multi-horizon:" + "c" * 32,
        request_id=f"multi-horizon-request:{request_hash[:24]}",
        request_hash=request_hash,
        target="TEST/USD",
        as_of_ms=1721235600000,
        horizon_order=[item["horizon"] for item in signals],
        reports=reports,
        graph_id="market.test_analysis",
        graph_version="1.0.0",
        graph_content_hash="b" * 64,
        formula_versions=dict(SOURCE_FORMULA_VERSIONS),
        created_at="2026-07-19T00:00:00+00:00",
        metadata={"fixture": "horizon-decision"},
    )


def _report(index: int, signal: dict) -> AnalysisReport:
    horizon = signal["horizon"]
    direction = signal["direction"]
    risk_level = "low"
    action_posture = "observe"
    decision = CellResult(
        cell_id="root.decision",
        name="DecisionCell",
        category="decision",
        target="TEST/USD",
        horizon=horizon,
        direction=direction,
        strength=float(signal["strength"]),
        confidence=float(signal["confidence"]),
        volatility_risk=float(signal["volatility_risk"]),
        manipulation_risk=float(signal["manipulation_risk"]),
        urgency=max(
            float(signal["strength"]),
            float(signal["volatility_risk"]),
            float(signal["manipulation_risk"]),
        ),
        score=float(signal["score"]),
        explanation="validation horizon signal",
        risk_level=risk_level,
        action_posture=action_posture,
        metadata={"formula_version": "decision_weighted_score_v0.5"},
    )
    return AnalysisReport(
        target="TEST/USD",
        horizon=horizon,
        decision=decision,
        summary="validation horizon report",
        run_id=f"run-{index}",
        report_id=f"report-{index}",
        engine_version="0.1.0",
        formula_versions=dict(SOURCE_FORMULA_VERSIONS),
        created_at="2026-07-19T00:00:00+00:00",
    )


if __name__ == "__main__":
    unittest.main()
