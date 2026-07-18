from __future__ import annotations

import math

from market_cell.cells.base import MarketCell
from market_cell.features import FEATURE_VERSION, build_feature_snapshot
from market_cell.models import AnalysisRequest, CellResult, Evidence
from market_cell.scoring import clamp, score


STRUCTURE_CELL_ID = "technical.support_resistance"
STRUCTURE_FORMULA_VERSION = "support_resistance_cluster_rejection_v0.1"
KNOWN_STRUCTURE_STATES = {
    "insufficient_history",
    "overlapping_levels",
    "support_broken_unconfirmed",
    "resistance_broken_unconfirmed",
    "two_sided_rejection",
    "support_rejection",
    "resistance_rejection",
    "testing_support",
    "testing_resistance",
    "unconfirmed_levels",
    "inside_range",
}
MINIMUM_VOLUME_RATIO = 1.2
MAXIMUM_VOLUME_BASELINE_CANDLES = 20


class BreakoutCell(MarketCell):
    cell_id = "technical.breakout"
    name = "BreakoutCell"
    category = "technical"
    description = "复核支撑压力结构破坏是否具备新鲜越界、强收盘和放量确认。"
    formula_version = "breakout_structure_volume_confirmation_v0.1"
    inputs = [
        "candles.open",
        "candles.high",
        "candles.low",
        "candles.close",
        "candles.volume",
        "child_results.technical.support_resistance",
    ]
    outputs = [
        "direction",
        "strength",
        "confidence",
        "breakout_state",
        "breakout_level",
        "volume_ratio",
    ]

    def analyze(
        self,
        request: AnalysisRequest,
        child_results: list[CellResult] | None = None,
    ) -> CellResult:
        structure = _required_structure_result(child_results)
        if (
            structure.target != request.target
            or structure.horizon != request.horizon
        ):
            raise ValueError(
                "BreakoutCell structure result target/horizon does not match request"
            )
        structure_formula_version = structure.metadata.get("formula_version")
        if structure_formula_version != STRUCTURE_FORMULA_VERSION:
            raise ValueError(
                "BreakoutCell requires support/resistance formula "
                f"{STRUCTURE_FORMULA_VERSION}"
            )
        structure_state = str(structure.metadata.get("structure_state", ""))
        if structure_state not in KNOWN_STRUCTURE_STATES:
            raise ValueError(
                f"BreakoutCell received unknown structure state {structure_state!r}"
            )
        if structure_state not in {
            "resistance_broken_unconfirmed",
            "support_broken_unconfirmed",
        }:
            return _non_candidate_result(
                cell=self,
                request=request,
                structure=structure,
                structure_state=structure_state,
            )
        if len(request.candles) < 2:
            raise ValueError("BreakoutCell requires at least two candles")

        upside = structure_state == "resistance_broken_unconfirmed"
        level_key = "resistance_level" if upside else "support_level"
        level = _required_metadata_number(structure, level_key)
        tolerance_pct = _required_metadata_number(
            structure,
            "zone_tolerance_pct",
        )
        touch_key = (
            "resistance_touch_count" if upside else "support_touch_count"
        )
        touch_value = _required_metadata_number(structure, touch_key)
        if level <= 0 or tolerance_pct <= 0:
            raise ValueError(
                "BreakoutCell structure level and tolerance must be positive"
            )
        if touch_value < 2 or not touch_value.is_integer():
            raise ValueError(
                "BreakoutCell structure touch count must be an integer of at least two"
            )
        touch_count = int(touch_value)
        previous = request.candles[-2]
        latest = request.candles[-1]
        threshold = level * (
            1 + tolerance_pct / 100 if upside else 1 - tolerance_pct / 100
        )
        fresh_cross = (
            previous.close <= threshold if upside else previous.close >= threshold
        )

        candle_range = latest.high - latest.low
        close_position = (
            (latest.close - latest.low) / candle_range if candle_range else 0.5
        )
        candle_confirmed = (
            latest.close > latest.open and close_position >= 0.7
            if upside
            else latest.close < latest.open and close_position <= 0.3
        )
        volume_window = request.candles[-(MAXIMUM_VOLUME_BASELINE_CANDLES + 1) :]
        volume_ratio = build_feature_snapshot(volume_window).latest_volume_ratio
        volume_confirmed = volume_ratio >= MINIMUM_VOLUME_RATIO
        displacement_pct = abs(latest.close - level) / level * 100

        failed_confirmations: list[str] = []
        if not fresh_cross:
            failed_confirmations.append("fresh_cross")
        if not candle_confirmed:
            failed_confirmations.append("strong_close")
        if not volume_confirmed:
            failed_confirmations.append("volume")

        candidate_direction = "bullish" if upside else "bearish"
        if failed_confirmations:
            direction = "conflict"
            breakout_state = _unconfirmed_state(failed_confirmations)
        else:
            direction = candidate_direction
            breakout_state = (
                "upside_breakout_confirmed"
                if upside
                else "downside_breakout_confirmed"
            )
        strength = _breakout_strength(
            confirmed=not failed_confirmations,
            displacement_pct=displacement_pct,
            volume_ratio=volume_ratio,
            close_position=close_position,
            upside=upside,
        )
        confidence = _breakout_confidence(
            structure_confidence=structure.confidence,
            touch_count=touch_count,
            fresh_cross=fresh_cross,
            candle_confirmed=candle_confirmed,
            volume_confirmed=volume_confirmed,
        )

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
            urgency=strength,
            score=score(direction, strength, confidence),
            explanation=_breakout_explanation(
                breakout_state=breakout_state,
                candidate_direction=candidate_direction,
                level=level,
                displacement_pct=displacement_pct,
                volume_ratio=volume_ratio,
                failed_confirmations=failed_confirmations,
            ),
            evidence=[
                Evidence(
                    source=structure.cell_id,
                    summary=(
                        f"structure_state={structure_state}, "
                        f"level={level:.4f}, touches={touch_count}, "
                        f"tolerance={tolerance_pct:.2f}%"
                    ),
                    reliability=structure.confidence,
                ),
                Evidence(
                    source="candles.close_volume",
                    summary=(
                        f"previous_close={previous.close:.4f}, "
                        f"latest_close={latest.close:.4f}, "
                        f"displacement={displacement_pct:.2f}%, "
                        f"volume_ratio={volume_ratio:.2f}, "
                        f"close_position={close_position:.2f}"
                    ),
                ),
            ],
            children=[structure],
            metadata={
                "breakout_state": breakout_state,
                "candidate_direction": candidate_direction,
                "structure_state": structure_state,
                "breakout_level": round(level, 4),
                "breakout_threshold": round(threshold, 4),
                "level_touch_count": touch_count,
                "zone_tolerance_pct": round(tolerance_pct, 4),
                "displacement_pct": round(displacement_pct, 4),
                "volume_ratio": round(volume_ratio, 4),
                "minimum_volume_ratio": MINIMUM_VOLUME_RATIO,
                "volume_baseline_candle_count": max(len(volume_window) - 1, 0),
                "maximum_volume_baseline_candles": (
                    MAXIMUM_VOLUME_BASELINE_CANDLES
                ),
                "fresh_cross": fresh_cross,
                "candle_confirmed": candle_confirmed,
                "volume_confirmed": volume_confirmed,
                "failed_confirmations": failed_confirmations,
                "feature_version": FEATURE_VERSION,
            },
        )


def _required_structure_result(
    child_results: list[CellResult] | None,
) -> CellResult:
    matches = [
        result
        for result in child_results or []
        if result.cell_id == STRUCTURE_CELL_ID
    ]
    if len(matches) != 1:
        raise ValueError(
            "BreakoutCell requires exactly one technical.support_resistance result"
        )
    return matches[0]


def _required_metadata_number(result: CellResult, key: str) -> float:
    value = result.metadata.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(
            f"{result.cell_id} metadata {key} must be a finite number"
        )
    return float(value)


def _non_candidate_result(
    *,
    cell: BreakoutCell,
    request: AnalysisRequest,
    structure: CellResult,
    structure_state: str,
) -> CellResult:
    breakout_state = (
        "insufficient_structure"
        if structure_state in {"", "insufficient_history", "unconfirmed_levels"}
        else "no_breakout_candidate"
    )
    return CellResult(
        cell_id=cell.cell_id,
        name=cell.name,
        category=cell.category,
        target=request.target,
        horizon=request.horizon,
        direction="neutral",
        strength=0,
        confidence=structure.confidence,
        volatility_risk=0,
        manipulation_risk=0,
        urgency=0,
        score=0,
        explanation=(
            f"支撑压力状态为 {structure_state or 'unknown'}，"
            "当前没有需要确认的结构突破。"
        ),
        evidence=[
            Evidence(
                source=structure.cell_id,
                summary=f"structure_state={structure_state or 'unknown'}",
                reliability=structure.confidence,
            )
        ],
        children=[structure],
        metadata={
            "breakout_state": breakout_state,
            "structure_state": structure_state or "unknown",
            "failed_confirmations": [],
        },
    )


def _unconfirmed_state(failed_confirmations: list[str]) -> str:
    if len(failed_confirmations) > 1:
        return "breakout_unconfirmed_multiple"
    return {
        "fresh_cross": "breakout_not_fresh",
        "strong_close": "breakout_unconfirmed_candle",
        "volume": "breakout_unconfirmed_volume",
    }[failed_confirmations[0]]


def _breakout_strength(
    *,
    confirmed: bool,
    displacement_pct: float,
    volume_ratio: float,
    close_position: float,
    upside: bool,
) -> float:
    if not confirmed:
        return clamp(20 + displacement_pct * 5, maximum=55)
    close_edge = close_position if upside else 1 - close_position
    return clamp(
        25
        + displacement_pct * 8
        + max(volume_ratio - 1, 0) * 20
        + close_edge * 15,
        maximum=88,
    )


def _breakout_confidence(
    *,
    structure_confidence: float,
    touch_count: int,
    fresh_cross: bool,
    candle_confirmed: bool,
    volume_confirmed: bool,
) -> float:
    return clamp(
        structure_confidence * 0.45
        + min(touch_count, 5) * 5
        + (12 if fresh_cross else 0)
        + (10 if candle_confirmed else 0)
        + (10 if volume_confirmed else 0),
        maximum=90,
    )


def _breakout_explanation(
    *,
    breakout_state: str,
    candidate_direction: str,
    level: float,
    displacement_pct: float,
    volume_ratio: float,
    failed_confirmations: list[str],
) -> str:
    if not failed_confirmations:
        direction_text = "向上" if candidate_direction == "bullish" else "向下"
        return (
            f"价格新鲜{direction_text}越过 {level:.4f}，"
            f"收盘偏离 {displacement_pct:.2f}%，成交量为基线的 "
            f"{volume_ratio:.2f} 倍，突破得到确认。"
        )
    failure_labels = {
        "fresh_cross": "不是本根 K 线首次越界",
        "strong_close": "收盘位置或实体方向不足",
        "volume": "成交量未达到确认阈值",
    }
    reasons = "；".join(failure_labels[item] for item in failed_confirmations)
    return (
        f"检测到候选结构突破（{breakout_state}），但{reasons}；"
        f"当前成交量为基线的 {volume_ratio:.2f} 倍，暂不确认方向。"
    )
