import unittest

from market_cell.cells.decision import DecisionCell
from market_cell.models import AnalysisRequest, Candle, CellResult


def child_result(
    cell_id: str,
    direction: str = "neutral",
    score: float = 0,
    volatility_risk: float = 0,
    manipulation_risk: float = 0,
) -> CellResult:
    return CellResult(
        cell_id=cell_id,
        name=cell_id,
        category="test",
        target="BTC/USD",
        horizon="1h",
        direction=direction,
        strength=abs(score),
        confidence=60,
        volatility_risk=volatility_risk,
        manipulation_risk=manipulation_risk,
        urgency=max(volatility_risk, manipulation_risk),
        score=score,
        explanation="test child result",
    )


class DecisionPolicyTests(unittest.TestCase):
    def test_decision_separates_bullish_direction_from_high_risk_posture(self):
        request = AnalysisRequest(
            target="BTC/USD",
            horizon="1h",
            candles=[
                Candle("t1", 100, 101, 99, 100, 1000),
            ],
        )
        result = DecisionCell().analyze(
            request,
            [
                child_result("technical.trend", direction="bullish", score=40),
                child_result("risk.manipulation", volatility_risk=60, manipulation_risk=42),
            ],
        )

        self.assertEqual(result.direction, "bullish")
        self.assertEqual(result.risk_level, "high")
        self.assertEqual(result.action_posture, "reduce_exposure")
        self.assertEqual(result.metadata["risk_breakdown"]["volatility_risk"], "high")
        self.assertIn("风险等级为偏高", result.explanation)


if __name__ == "__main__":
    unittest.main()
