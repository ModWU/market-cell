from market_cell.cells.base import MarketCell
from market_cell.features import FEATURE_VERSION, build_feature_snapshot
from market_cell.models import AnalysisRequest, CellResult, Evidence
from market_cell.scoring import clamp, score


class MarketRegimeCell(MarketCell):
    cell_id = "technical.market_regime"
    name = "MarketRegimeCell"
    category = "technical"
    description = "识别当前市场状态：趋势、震荡、剧烈震荡或方向不明。"
    formula_version = "trend_efficiency_regime_v0.1"
    inputs = ["candles.high", "candles.low", "candles.close"]
    outputs = ["market_regime", "direction", "volatility_risk", "urgency"]
    risk_dimensions = ["volatility_risk"]

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
                explanation="K 线数量不足，无法判断市场状态。",
                metadata={"market_regime": "unknown"},
            )

        features = build_feature_snapshot(candles)
        total_move_pct = features.total_move_pct
        path_distance = features.path_distance_pct
        trend_efficiency = features.trend_efficiency
        average_range_pct = features.average_range_pct

        if average_range_pct >= 2.8 and trend_efficiency < 0.45:
            market_regime = "volatile_range"
            direction = "conflict"
        elif abs(total_move_pct) >= 2.0 and trend_efficiency >= 0.45:
            market_regime = "trend_up" if total_move_pct > 0 else "trend_down"
            direction = "bullish" if total_move_pct > 0 else "bearish"
        elif trend_efficiency < 0.35:
            market_regime = "range"
            direction = "neutral"
        else:
            market_regime = "mixed"
            direction = "conflict"

        strength = clamp(max(abs(total_move_pct) * 7, trend_efficiency * 100))
        volatility_risk = clamp(average_range_pct * 18)
        confidence = clamp(35 + len(candles) * 4, maximum=82)
        urgency = clamp(max(volatility_risk, strength if direction == "conflict" else strength * 0.7))

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
            urgency=urgency,
            score=score(direction, strength, confidence),
            explanation=(
                f"市场状态识别为 {market_regime}，趋势效率 {trend_efficiency:.2f}，"
                f"平均振幅 {average_range_pct:.2f}%。"
            ),
            evidence=[
                Evidence(
                    source="candles.market_regime",
                    summary=(
                        f"total_move={total_move_pct:.2f}%, path_distance={path_distance:.2f}%, "
                        f"trend_efficiency={trend_efficiency:.2f}"
                    ),
                )
            ],
            metadata={
                "market_regime": market_regime,
                "total_move_pct": round(total_move_pct, 4),
                "trend_efficiency": round(trend_efficiency, 4),
                "average_range_pct": round(average_range_pct, 4),
                "feature_version": FEATURE_VERSION,
            },
        )
