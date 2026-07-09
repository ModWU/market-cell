from market_cell.cells.base import MarketCell
from market_cell.models import AnalysisRequest, CellResult, Evidence
from market_cell.scoring import clamp, score


class ManipulationRiskCell(MarketCell):
    cell_id = "risk.manipulation"
    name = "ManipulationRiskCell"
    category = "risk"
    description = "通过异常放量、剧烈振幅和长影线形态估计人为操纵或流动性异常风险。"
    formula_version = "price_volume_shape_manipulation_v0.1"
    inputs = ["candles.open", "candles.high", "candles.low", "candles.close", "candles.volume"]
    outputs = ["manipulation_risk", "volatility_risk", "urgency"]
    risk_dimensions = ["manipulation_risk", "volatility_risk"]

    def analyze(self, request: AnalysisRequest, child_results: list[CellResult] | None = None) -> CellResult:
        candles = request.candles
        if len(candles) < 4:
            return CellResult(
                cell_id=self.cell_id,
                name=self.name,
                category=self.category,
                target=request.target,
                horizon=request.horizon,
                direction="neutral",
                strength=0,
                confidence=15,
                volatility_risk=0,
                manipulation_risk=0,
                urgency=0,
                score=0,
                explanation="K 线数量不足，无法判断操纵风险。",
            )

        latest = candles[-1]
        prev = candles[:-1]
        avg_volume = sum(item.volume for item in prev) / len(prev)
        volume_ratio = latest.volume / avg_volume if avg_volume else 1
        latest_range = (latest.high - latest.low) / latest.close * 100 if latest.close else 0
        body = abs(latest.close - latest.open)
        wick_total = max((latest.high - latest.low) - body, 0)
        wick_ratio = wick_total / (latest.high - latest.low) if latest.high != latest.low else 0

        risk = 0.0
        evidence: list[Evidence] = []

        if volume_ratio > 2.0:
            risk += clamp((volume_ratio - 2.0) * 22, maximum=40)
            evidence.append(
                Evidence(
                    source="volume_spike",
                    summary=f"最新成交量达到前序均量 {volume_ratio:.2f} 倍，存在异常放量。",
                )
            )

        if latest_range > 4.0:
            risk += clamp((latest_range - 4.0) * 8, maximum=30)
            evidence.append(
                Evidence(
                    source="large_intraperiod_range",
                    summary=f"最新 K 线振幅 {latest_range:.2f}%，短周期剧烈波动。",
                )
            )

        if wick_ratio > 0.55:
            risk += clamp((wick_ratio - 0.55) * 60, maximum=25)
            evidence.append(
                Evidence(
                    source="long_wick",
                    summary=f"最新 K 线影线占比 {wick_ratio:.2f}，存在拉升回落或砸盘回收痕迹。",
                )
            )

        manipulation_risk = clamp(risk)
        direction = "conflict" if manipulation_risk >= 35 else "neutral"
        confidence = clamp(35 + len(evidence) * 16)

        if not evidence:
            evidence.append(Evidence(source="price_volume_shape", summary="当前样本没有明显操纵风险特征。"))

        return CellResult(
            cell_id=self.cell_id,
            name=self.name,
            category=self.category,
            target=request.target,
            horizon=request.horizon,
            direction=direction,
            strength=manipulation_risk,
            confidence=confidence,
            volatility_risk=clamp(latest_range * 14),
            manipulation_risk=manipulation_risk,
            urgency=manipulation_risk,
            score=score(direction, manipulation_risk, confidence),
            explanation=f"操纵风险估计为 {manipulation_risk:.1f}/100，结论为 {direction}。",
            evidence=evidence,
            metadata={
                "volume_ratio": round(volume_ratio, 4),
                "latest_range_pct": round(latest_range, 4),
                "wick_ratio": round(wick_ratio, 4),
            },
        )
