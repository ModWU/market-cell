from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from market_cell.models import ActionPosture, CellResult, Direction, RiskLevel
from market_cell.scoring import clamp, direction_from_score, weighted_average


DEFAULT_DECISION_WEIGHTS = {
    "technical.trend": 1.2,
    "technical.volume": 0.9,
    "technical.volatility": 0.8,
    "technical.market_regime": 1.0,
    "external.news": 0.8,
    "risk.manipulation": 1.1,
}

RISK_LEVEL_RANK: dict[RiskLevel, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "extreme": 3,
}

RISK_LEVEL_LABELS: dict[RiskLevel, str] = {
    "low": "低",
    "medium": "中等",
    "high": "偏高",
    "extreme": "极高",
}


@dataclass(frozen=True)
class RiskThresholds:
    medium: float
    high: float
    extreme: float

    def level_for(self, value: float) -> RiskLevel:
        if value >= self.extreme:
            return "extreme"
        if value >= self.high:
            return "high"
        if value >= self.medium:
            return "medium"
        return "low"


@dataclass(frozen=True)
class DecisionAssessment:
    aggregate_score: float
    direction: Direction
    strength: float
    confidence: float
    volatility_risk: float
    manipulation_risk: float
    urgency: float
    risk_level: RiskLevel
    action_posture: ActionPosture
    risk_notes: list[str]
    risk_breakdown: dict[str, RiskLevel]
    explanation: str


@dataclass(frozen=True)
class DecisionPolicy:
    """Strategy object for root decision scoring and risk posture."""

    formula_version: str = "decision_weighted_score_v0.2"
    weights: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_DECISION_WEIGHTS))
    volatility_thresholds: RiskThresholds = RiskThresholds(medium=35, high=55, extreme=75)
    manipulation_thresholds: RiskThresholds = RiskThresholds(medium=25, high=35, extreme=65)

    def evaluate(self, child_results: Iterable[CellResult]) -> DecisionAssessment:
        children = list(child_results)
        aggregate_score = weighted_average(children, dict(self.weights))
        direction = direction_from_score(aggregate_score)
        strength = clamp(abs(aggregate_score) * 1.7)
        confidence = clamp(sum(item.confidence for item in children) / len(children)) if children else 0
        volatility_risk = max((item.volatility_risk for item in children), default=0)
        manipulation_risk = max((item.manipulation_risk for item in children), default=0)
        urgency = clamp(max(volatility_risk, manipulation_risk, strength))

        risk_breakdown = {
            "volatility_risk": self.volatility_thresholds.level_for(volatility_risk),
            "manipulation_risk": self.manipulation_thresholds.level_for(manipulation_risk),
        }
        risk_level = self.overall_risk_level(risk_breakdown.values())
        action_posture = self.action_posture(direction, risk_level)
        risk_notes = self.risk_notes(risk_breakdown)
        explanation = self.explanation(direction, risk_level, risk_notes, action_posture)

        return DecisionAssessment(
            aggregate_score=aggregate_score,
            direction=direction,
            strength=strength,
            confidence=confidence,
            volatility_risk=volatility_risk,
            manipulation_risk=manipulation_risk,
            urgency=urgency,
            risk_level=risk_level,
            action_posture=action_posture,
            risk_notes=risk_notes,
            risk_breakdown=risk_breakdown,
            explanation=explanation,
        )

    def overall_risk_level(self, levels: Iterable[RiskLevel]) -> RiskLevel:
        return max(levels, key=lambda level: RISK_LEVEL_RANK[level], default="low")

    def action_posture(self, direction: Direction, risk_level: RiskLevel) -> ActionPosture:
        if risk_level == "extreme":
            return "avoid_chasing"
        if risk_level == "high":
            return "reduce_exposure"
        if risk_level == "medium":
            return "wait_for_confirmation"
        if direction in {"bullish", "bearish"}:
            return "cautious_follow"
        return "observe"

    def risk_notes(self, risk_breakdown: Mapping[str, RiskLevel]) -> list[str]:
        notes: list[str] = []
        volatility_level = risk_breakdown["volatility_risk"]
        manipulation_level = risk_breakdown["manipulation_risk"]

        if volatility_level != "low":
            notes.append(f"波动风险{RISK_LEVEL_LABELS[volatility_level]}")
        if manipulation_level != "low":
            notes.append(f"操纵风险{RISK_LEVEL_LABELS[manipulation_level]}")
        if not notes:
            notes.append("未发现突出的极端风险")
        return notes

    def explanation(
        self,
        direction: Direction,
        risk_level: RiskLevel,
        risk_notes: list[str],
        action_posture: ActionPosture,
    ) -> str:
        direction_text = {
            "bullish": "短线偏多",
            "bearish": "短线偏空",
            "conflict": "多空因素冲突",
            "neutral": "方向不明确",
        }[direction]
        action_text = {
            "observe": "更适合观察，等待更明确证据",
            "wait_for_confirmation": "更适合等待确认或轻量验证，避免重仓追逐",
            "cautious_follow": "可以关注顺势机会，但仍需保留风险控制",
            "reduce_exposure": "更适合降低风险暴露，等待结构重新稳定",
            "avoid_chasing": "不适合追逐当前波动，优先保护本金和流动性",
        }[action_posture]
        risk_text = "，".join(risk_notes)
        return (
            f"{direction_text}。当前风险等级为{RISK_LEVEL_LABELS[risk_level]}，"
            f"主要风险：{risk_text}；{action_text}。"
        )
