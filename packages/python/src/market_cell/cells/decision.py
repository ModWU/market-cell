from market_cell.cells.base import MarketCell
from market_cell.models import AnalysisRequest, CellResult, Evidence
from market_cell.policies import DecisionPolicy


class DecisionCell(MarketCell):
    cell_id = "root.decision"
    name = "DecisionCell"
    category = "decision"
    description = "聚合所有子 Cell 的方向、置信度和风险，形成根节点分析结论。"
    formula_version = "decision_weighted_score_v0.2"
    inputs = ["child_results.score", "child_results.risk"]
    outputs = ["direction", "strength", "confidence", "volatility_risk", "manipulation_risk", "summary"]
    risk_dimensions = ["volatility_risk", "manipulation_risk"]

    def __init__(self, policy: DecisionPolicy | None = None) -> None:
        self.policy = policy or DecisionPolicy()
        self.formula_version = self.policy.formula_version

    def analyze(self, request: AnalysisRequest, child_results: list[CellResult] | None = None) -> CellResult:
        children = child_results or []
        assessment = self.policy.evaluate(children)

        evidence = [
            Evidence(
                source=item.cell_id,
                summary=f"{item.name}: direction={item.direction}, score={item.score}, risk=({item.volatility_risk:.1f}, {item.manipulation_risk:.1f})",
                weight=self.policy.weights.get(item.cell_id, 1.0),
            )
            for item in children
        ]

        return CellResult(
            cell_id=self.cell_id,
            name=self.name,
            category=self.category,
            target=request.target,
            horizon=request.horizon,
            direction=assessment.direction,
            strength=assessment.strength,
            confidence=assessment.confidence,
            volatility_risk=assessment.volatility_risk,
            manipulation_risk=assessment.manipulation_risk,
            urgency=assessment.urgency,
            score=assessment.aggregate_score,
            explanation=assessment.explanation,
            risk_level=assessment.risk_level,
            action_posture=assessment.action_posture,
            evidence=evidence,
            children=children,
            metadata={
                "formula_version": self.policy.formula_version,
                "weights": dict(self.policy.weights),
                "risk_notes": assessment.risk_notes,
                "risk_breakdown": assessment.risk_breakdown,
            },
        )
