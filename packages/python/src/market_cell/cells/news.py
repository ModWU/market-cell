from market_cell.cells.base import MarketCell
from market_cell.models import AnalysisRequest, CellResult, Evidence
from market_cell.scoring import clamp, score


class NewsEventCell(MarketCell):
    cell_id = "external.news"
    name = "NewsEventCell"
    category = "external"
    description = "聚合外部事件的情绪、影响力和新鲜度，估计事件对目标资产的方向影响。"
    formula_version = "weighted_event_sentiment_v0.1"
    inputs = ["events.sentiment", "events.impact", "events.freshness"]
    outputs = ["direction", "strength", "confidence", "volatility_risk"]
    risk_dimensions = ["volatility_risk"]

    def analyze(self, request: AnalysisRequest, child_results: list[CellResult] | None = None) -> CellResult:
        if not request.events:
            return CellResult(
                cell_id=self.cell_id,
                name=self.name,
                category=self.category,
                target=request.target,
                horizon=request.horizon,
                direction="neutral",
                strength=0,
                confidence=20,
                volatility_risk=0,
                manipulation_risk=0,
                urgency=0,
                score=0,
                explanation="没有输入外部事件，新闻 Cell 保持中性。",
            )

        weighted_sentiment = 0.0
        total_weight = 0.0
        evidence: list[Evidence] = []
        for event in request.events:
            weight = clamp(event.impact) * clamp(event.freshness) / 100.0
            weighted_sentiment += event.sentiment * weight
            total_weight += weight
            evidence.append(
                Evidence(
                    source=f"event.{event.category}",
                    summary=event.title,
                    weight=round(weight, 4),
                    freshness=event.freshness,
                )
            )

        normalized = weighted_sentiment / total_weight if total_weight else 0
        direction = "bullish" if normalized > 0.15 else "bearish" if normalized < -0.15 else "neutral"
        strength = clamp(abs(normalized) * 100)
        confidence = clamp(35 + min(len(request.events), 5) * 10)
        volatility_risk = clamp(total_weight / max(len(request.events), 1) * 0.4)

        return CellResult(
            cell_id=self.cell_id,
            name=self.name,
            category=self.category,
            target=request.target,
            horizon=request.horizon,
            direction=direction,
            strength=strength,
            confidence=confidence,
            volatility_risk=volatility_risk,
            manipulation_risk=0,
            urgency=volatility_risk,
            score=score(direction, strength, confidence),
            explanation=f"外部事件加权情绪为 {normalized:.2f}，方向为 {direction}。",
            evidence=evidence,
            metadata={"weighted_sentiment": round(normalized, 4), "event_count": len(request.events)},
        )
