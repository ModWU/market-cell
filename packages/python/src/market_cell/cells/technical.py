from market_cell.cells.base import MarketCell
from market_cell.features import FEATURE_VERSION, build_feature_snapshot
from market_cell.models import AnalysisRequest, CellResult, Evidence
from market_cell.scoring import clamp, score


def _confidence_from_candle_count(count: int) -> float:
    return clamp(35 + count * 4, maximum=85)


class TrendCell(MarketCell):
    cell_id = "technical.trend"
    name = "TrendCell"
    category = "technical"
    description = "分析首尾收盘价变化，判断当前样本周期内的基础趋势方向。"
    formula_version = "trend_close_change_v0.1"
    inputs = ["candles.open", "candles.close"]
    outputs = ["direction", "strength", "confidence", "score"]

    def analyze(self, request: AnalysisRequest, child_results: list[CellResult] | None = None) -> CellResult:
        candles = request.candles
        if len(candles) < 2:
            return CellResult(
                cell_id=self.cell_id,
                name=self.name,
                category=self.category,
                target=request.target,
                horizon=request.horizon,
                direction="neutral",
                strength=0,
                confidence=10,
                volatility_risk=0,
                manipulation_risk=0,
                urgency=0,
                score=0,
                explanation="K 线数量不足，无法判断趋势。",
            )

        features = build_feature_snapshot(candles)
        first = features.first_close or 0
        last = features.last_close or 0
        change_pct = features.close_change_pct
        direction = "bullish" if change_pct > 1 else "bearish" if change_pct < -1 else "neutral"
        strength = clamp(abs(change_pct) * 6)
        confidence = _confidence_from_candle_count(len(candles))

        return CellResult(
            cell_id=self.cell_id,
            name=self.name,
            category=self.category,
            target=request.target,
            horizon=request.horizon,
            direction=direction,
            strength=strength,
            confidence=confidence,
            volatility_risk=0,
            manipulation_risk=0,
            urgency=clamp(abs(change_pct) * 4),
            score=score(direction, strength, confidence),
            explanation=f"首尾收盘价变化 {change_pct:.2f}%，趋势方向为 {direction}。",
            evidence=[
                Evidence(
                    source="candles.close",
                    summary=f"first_close={first:.2f}, last_close={last:.2f}, change={change_pct:.2f}%",
                )
            ],
            metadata={"change_pct": round(change_pct, 4), "feature_version": FEATURE_VERSION},
        )


class VolumeCell(MarketCell):
    cell_id = "technical.volume"
    name = "VolumeCell"
    category = "technical"
    description = "比较最新成交量和历史均量，只判断量能是否支持价格方向。"
    formula_version = "volume_direction_confirmation_v0.2"
    inputs = ["candles.close", "candles.volume"]
    outputs = ["direction", "strength", "urgency", "volume_ratio"]

    def analyze(self, request: AnalysisRequest, child_results: list[CellResult] | None = None) -> CellResult:
        candles = request.candles
        if len(candles) < 3:
            return CellResult(
                cell_id=self.cell_id,
                name=self.name,
                category=self.category,
                target=request.target,
                horizon=request.horizon,
                direction="neutral",
                strength=0,
                confidence=10,
                volatility_risk=0,
                manipulation_risk=0,
                urgency=0,
                score=0,
                explanation="K 线数量不足，无法判断成交量结构。",
            )

        features = build_feature_snapshot(candles)
        avg_volume = features.previous_average_volume
        latest = candles[-1]
        ratio = features.latest_volume_ratio
        price_change = features.latest_close_change

        if ratio > 1.25 and price_change > 0:
            direction = "bullish"
        elif ratio > 1.25 and price_change < 0:
            direction = "bearish"
        else:
            direction = "neutral"

        strength = clamp((ratio - 1) * 45)
        confidence = _confidence_from_candle_count(len(candles))
        return CellResult(
            cell_id=self.cell_id,
            name=self.name,
            category=self.category,
            target=request.target,
            horizon=request.horizon,
            direction=direction,
            strength=strength,
            confidence=confidence,
            volatility_risk=0,
            manipulation_risk=0,
            urgency=clamp((ratio - 1) * 35),
            score=score(direction, strength, confidence),
            explanation=f"最新成交量是前序均量的 {ratio:.2f} 倍，量能方向为 {direction}。",
            evidence=[
                Evidence(
                    source="candles.volume",
                    summary=f"latest_volume={latest.volume:.2f}, average_volume={avg_volume:.2f}, ratio={ratio:.2f}",
                )
            ],
            metadata={
                "formula_version": self.formula_version,
                "volume_ratio": round(ratio, 4),
                "feature_version": FEATURE_VERSION,
                "anomaly_risk_delegated_to": "risk.volume_price_anomaly",
            },
        )


class VolatilityCell(MarketCell):
    cell_id = "technical.volatility"
    name = "VolatilityCell"
    category = "risk"
    description = "用 K 线高低点振幅估计当前周期的波动风险。"
    formula_version = "average_range_volatility_v0.1"
    inputs = ["candles.high", "candles.low", "candles.close"]
    outputs = ["volatility_risk", "urgency"]
    risk_dimensions = ["volatility_risk"]

    def analyze(self, request: AnalysisRequest, child_results: list[CellResult] | None = None) -> CellResult:
        candles = request.candles
        if len(candles) < 2:
            return CellResult(
                cell_id=self.cell_id,
                name=self.name,
                category=self.category,
                target=request.target,
                horizon=request.horizon,
                direction="neutral",
                strength=0,
                confidence=10,
                volatility_risk=0,
                manipulation_risk=0,
                urgency=0,
                score=0,
                explanation="K 线数量不足，无法判断波动率。",
            )

        features = build_feature_snapshot(candles)
        avg_range = features.average_range_pct
        volatility_risk = clamp(avg_range * 16)
        direction = "conflict" if volatility_risk > 55 else "neutral"
        confidence = _confidence_from_candle_count(len(candles))

        return CellResult(
            cell_id=self.cell_id,
            name=self.name,
            category=self.category,
            target=request.target,
            horizon=request.horizon,
            direction=direction,
            strength=volatility_risk,
            confidence=confidence,
            volatility_risk=volatility_risk,
            manipulation_risk=0,
            urgency=volatility_risk,
            score=score(direction, volatility_risk, confidence),
            explanation=f"平均单根振幅约 {avg_range:.2f}%，波动风险为 {volatility_risk:.1f}/100。",
            evidence=[
                Evidence(
                    source="candles.high_low_range",
                    summary=f"average_range={avg_range:.2f}%, volatility_risk={volatility_risk:.1f}",
                )
            ],
            metadata={"average_range_pct": round(avg_range, 4), "feature_version": FEATURE_VERSION},
        )
