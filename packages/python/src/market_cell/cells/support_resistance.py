from __future__ import annotations

from dataclasses import dataclass

from market_cell.cells.base import MarketCell
from market_cell.features import FEATURE_VERSION, build_feature_snapshot
from market_cell.models import AnalysisRequest, Candle, CellResult, Evidence
from market_cell.scoring import clamp, score


MINIMUM_CANDLE_COUNT = 6
MINIMUM_LEVEL_TOUCHES = 2
MAXIMUM_HISTORY_CANDLE_COUNT = 48


@dataclass(frozen=True)
class _PriceCluster:
    level: float
    touch_count: int
    spread_pct: float


class SupportResistanceCell(MarketCell):
    cell_id = "technical.support_resistance"
    name = "SupportResistanceCell"
    category = "technical"
    description = "识别重复触及的支撑和压力区，并只在最新 K 线明确拒绝该区间时给出方向。"
    formula_version = "support_resistance_cluster_rejection_v0.1"
    inputs = ["candles.open", "candles.high", "candles.low", "candles.close"]
    outputs = [
        "direction",
        "strength",
        "confidence",
        "support_level",
        "resistance_level",
        "structure_state",
    ]

    def analyze(
        self,
        request: AnalysisRequest,
        child_results: list[CellResult] | None = None,
    ) -> CellResult:
        candles = request.candles
        if len(candles) < MINIMUM_CANDLE_COUNT:
            return self._insufficient_history_result(request)

        history = candles[-(MAXIMUM_HISTORY_CANDLE_COUNT + 1) : -1]
        latest = candles[-1]
        history_features = build_feature_snapshot(history)
        tolerance_pct = clamp(
            history_features.average_range_pct * 0.35,
            minimum=0.25,
            maximum=1.5,
        )
        support = _densest_price_cluster(
            [candle.low for candle in history],
            tolerance_pct,
            prefer_higher=False,
        )
        resistance = _densest_price_cluster(
            [candle.high for candle in history],
            tolerance_pct,
            prefer_higher=True,
        )
        support_confirmed = support.touch_count >= MINIMUM_LEVEL_TOUCHES
        resistance_confirmed = resistance.touch_count >= MINIMUM_LEVEL_TOUCHES
        support_level = support.level if support_confirmed else None
        resistance_level = resistance.level if resistance_confirmed else None

        state, direction, active_touches, rejection_ratio, break_distance_pct = (
            _classify_structure(
                latest=latest,
                support_level=support_level,
                resistance_level=resistance_level,
                support_touches=support.touch_count,
                resistance_touches=resistance.touch_count,
                tolerance_pct=tolerance_pct,
            )
        )
        confidence = _confidence(
            history_count=len(history),
            support_touches=support.touch_count if support_confirmed else 0,
            resistance_touches=(
                resistance.touch_count if resistance_confirmed else 0
            ),
            state=state,
        )
        strength = _strength(
            direction=direction,
            active_touches=active_touches,
            rejection_ratio=rejection_ratio,
            break_distance_pct=break_distance_pct,
        )
        support_distance_pct = _distance_pct(latest.close, support_level)
        resistance_distance_pct = _distance_pct(latest.close, resistance_level)

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
            urgency=strength if direction != "neutral" else 0,
            score=score(direction, strength, confidence),
            explanation=_explanation(
                state=state,
                support_level=support_level,
                resistance_level=resistance_level,
                tolerance_pct=tolerance_pct,
            ),
            evidence=[
                Evidence(
                    source="candles.high_low_clusters",
                    summary=(
                        f"support={_format_level(support_level)} "
                        f"({support.touch_count} touches), "
                        f"resistance={_format_level(resistance_level)} "
                        f"({resistance.touch_count} touches), "
                        f"tolerance={tolerance_pct:.2f}%"
                    ),
                    reliability=clamp(
                        45 + max(support.touch_count, resistance.touch_count) * 8,
                        maximum=90,
                    ),
                ),
                Evidence(
                    source="candles.latest",
                    summary=(
                        f"open={latest.open:.4f}, high={latest.high:.4f}, "
                        f"low={latest.low:.4f}, close={latest.close:.4f}, "
                        f"state={state}"
                    ),
                ),
            ],
            metadata={
                "formula_version": self.formula_version,
                "structure_state": state,
                "support_level": _rounded_or_none(support_level),
                "resistance_level": _rounded_or_none(resistance_level),
                "support_touch_count": support.touch_count,
                "resistance_touch_count": resistance.touch_count,
                "support_cluster_spread_pct": round(support.spread_pct, 4),
                "resistance_cluster_spread_pct": round(
                    resistance.spread_pct,
                    4,
                ),
                "support_distance_pct": _rounded_or_none(support_distance_pct),
                "resistance_distance_pct": _rounded_or_none(
                    resistance_distance_pct
                ),
                "zone_tolerance_pct": round(tolerance_pct, 4),
                "minimum_level_touches": MINIMUM_LEVEL_TOUCHES,
                "history_candle_count": len(history),
                "maximum_history_candle_count": MAXIMUM_HISTORY_CANDLE_COUNT,
                "feature_version": FEATURE_VERSION,
            },
        )

    def _insufficient_history_result(
        self,
        request: AnalysisRequest,
    ) -> CellResult:
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
            explanation=(
                f"至少需要 {MINIMUM_CANDLE_COUNT} 根 K 线，"
                "才能从历史触点识别支撑和压力。"
            ),
            metadata={
                "formula_version": self.formula_version,
                "structure_state": "insufficient_history",
                "minimum_candle_count": MINIMUM_CANDLE_COUNT,
                "actual_candle_count": len(request.candles),
            },
        )


def _densest_price_cluster(
    values: list[float],
    tolerance_pct: float,
    *,
    prefer_higher: bool,
) -> _PriceCluster:
    best_cluster: _PriceCluster | None = None
    best_rank: tuple[float, ...] | None = None
    for anchor in values:
        members: list[float] = []
        for value in values:
            distance_pct = _distance_pct(value, anchor)
            if distance_pct is not None and distance_pct <= tolerance_pct:
                members.append(value)
        level = sum(members) / len(members)
        spread_pct = (
            (max(members) - min(members)) / level * 100 if level else 0
        )
        cluster = _PriceCluster(
            level=level,
            touch_count=len(members),
            spread_pct=spread_pct,
        )
        price_rank = -level if prefer_higher else level
        rank = (-cluster.touch_count, cluster.spread_pct, price_rank)
        if best_rank is None or rank < best_rank:
            best_cluster = cluster
            best_rank = rank
    if best_cluster is None:
        raise ValueError("price cluster requires at least one value")
    return best_cluster


def _classify_structure(
    *,
    latest: Candle,
    support_level: float | None,
    resistance_level: float | None,
    support_touches: int,
    resistance_touches: int,
    tolerance_pct: float,
) -> tuple[str, str, int, float, float]:
    if (
        support_level is not None
        and resistance_level is not None
        and support_level >= resistance_level
    ):
        return "overlapping_levels", "conflict", 0, 0, 0

    support_break_distance = _downside_break_distance_pct(
        latest.close,
        support_level,
        tolerance_pct,
    )
    resistance_break_distance = _upside_break_distance_pct(
        latest.close,
        resistance_level,
        tolerance_pct,
    )
    if support_break_distance > 0:
        return (
            "support_broken_unconfirmed",
            "conflict",
            support_touches,
            0,
            support_break_distance,
        )
    if resistance_break_distance > 0:
        return (
            "resistance_broken_unconfirmed",
            "conflict",
            resistance_touches,
            0,
            resistance_break_distance,
        )

    candle_range = latest.high - latest.low
    close_position = (
        (latest.close - latest.low) / candle_range if candle_range else 0.5
    )
    lower_wick_ratio = (
        (min(latest.open, latest.close) - latest.low) / candle_range
        if candle_range
        else 0
    )
    upper_wick_ratio = (
        (latest.high - max(latest.open, latest.close)) / candle_range
        if candle_range
        else 0
    )
    support_tested = (
        support_level is not None
        and latest.low <= support_level * (1 + tolerance_pct / 100)
        and latest.high >= support_level * (1 - tolerance_pct / 100)
    )
    resistance_tested = (
        resistance_level is not None
        and latest.high >= resistance_level * (1 - tolerance_pct / 100)
        and latest.low <= resistance_level * (1 + tolerance_pct / 100)
    )
    support_rejection = (
        support_tested
        and latest.close >= support_level
        and latest.close >= latest.open
        and close_position >= 0.6
    )
    resistance_rejection = (
        resistance_tested
        and latest.close <= resistance_level
        and latest.close <= latest.open
        and close_position <= 0.4
    )

    if support_tested and resistance_tested:
        return (
            "two_sided_rejection",
            "conflict",
            max(support_touches, resistance_touches),
            max(lower_wick_ratio, upper_wick_ratio),
            0,
        )
    if support_rejection:
        return (
            "support_rejection",
            "bullish",
            support_touches,
            lower_wick_ratio,
            0,
        )
    if resistance_rejection:
        return (
            "resistance_rejection",
            "bearish",
            resistance_touches,
            upper_wick_ratio,
            0,
        )
    if support_tested:
        return "testing_support", "neutral", support_touches, 0, 0
    if resistance_tested:
        return "testing_resistance", "neutral", resistance_touches, 0, 0
    if support_level is None and resistance_level is None:
        return "unconfirmed_levels", "neutral", 0, 0, 0
    return "inside_range", "neutral", 0, 0, 0


def _confidence(
    *,
    history_count: int,
    support_touches: int,
    resistance_touches: int,
    state: str,
) -> float:
    confirmed_touch_count = max(support_touches, resistance_touches)
    value = clamp(
        25 + history_count * 3 + max(confirmed_touch_count - 1, 0) * 8,
        maximum=88,
    )
    if state == "unconfirmed_levels":
        return min(value, 40)
    return value


def _strength(
    *,
    direction: str,
    active_touches: int,
    rejection_ratio: float,
    break_distance_pct: float,
) -> float:
    if direction in {"bullish", "bearish"}:
        return clamp(
            20 + min(active_touches, 4) * 8 + rejection_ratio * 25,
            maximum=80,
        )
    if direction == "conflict":
        return clamp(
            20 + min(active_touches, 4) * 5 + break_distance_pct * 15,
            maximum=75,
        )
    return 0


def _downside_break_distance_pct(
    close: float,
    support_level: float | None,
    tolerance_pct: float,
) -> float:
    if support_level is None:
        return 0
    threshold = support_level * (1 - tolerance_pct / 100)
    return max((threshold - close) / support_level * 100, 0)


def _upside_break_distance_pct(
    close: float,
    resistance_level: float | None,
    tolerance_pct: float,
) -> float:
    if resistance_level is None:
        return 0
    threshold = resistance_level * (1 + tolerance_pct / 100)
    return max((close - threshold) / resistance_level * 100, 0)


def _distance_pct(value: float, reference: float | None) -> float | None:
    if reference is None or reference == 0:
        return None
    return abs(value - reference) / reference * 100


def _rounded_or_none(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _format_level(value: float | None) -> str:
    return f"{value:.4f}" if value is not None else "unconfirmed"


def _explanation(
    *,
    state: str,
    support_level: float | None,
    resistance_level: float | None,
    tolerance_pct: float,
) -> str:
    level_text = (
        f"支撑 {_format_level(support_level)}，"
        f"压力 {_format_level(resistance_level)}，"
        f"区间容差 {tolerance_pct:.2f}%"
    )
    state_text = {
        "support_rejection": "最新 K 线测试支撑后收回，形成偏多拒绝信号",
        "resistance_rejection": "最新 K 线测试压力后回落，形成偏空拒绝信号",
        "support_broken_unconfirmed": (
            "最新收盘破坏支撑，但单次收盘不足以确认有效向下突破"
        ),
        "resistance_broken_unconfirmed": (
            "最新收盘突破压力，但单次收盘不足以确认有效向上突破"
        ),
        "testing_support": "最新 K 线正在测试支撑，尚未形成明确拒绝",
        "testing_resistance": "最新 K 线正在测试压力，尚未形成明确拒绝",
        "inside_range": "最新价格仍位于已确认区间内部",
        "unconfirmed_levels": "历史触点不足，暂未形成可靠支撑或压力",
        "overlapping_levels": "支撑与压力区重叠，结构无法可靠区分",
        "two_sided_rejection": "最新 K 线同时触及两侧区域，结构信号冲突",
    }[state]
    return f"{level_text}；{state_text}。"
