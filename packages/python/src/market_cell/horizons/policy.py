from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable, Mapping

from market_cell.data.timeframes import interval_to_millis
from market_cell.horizons.decision_models import (
    HorizonAlignmentStatus,
    HorizonBand,
    HorizonBandDecision,
    HorizonConflictType,
    HorizonSignal,
)
from market_cell.models import ActionPosture, Direction, RiskLevel
from market_cell.policies.decision import (
    RISK_LEVEL_RANK,
    RiskThresholds,
)
from market_cell.scoring import clamp


HORIZON_DECISION_FORMULA_VERSION = "horizon_structure_alignment_v0.1"

SHORT_BAND_MAX_MS = 4 * 3_600_000
LONG_BAND_MIN_MS = 7 * 86_400_000

DEFAULT_BAND_AUTHORITY: dict[HorizonBand, float] = {
    "short": 0.2,
    "medium": 0.3,
    "long": 0.5,
}

_BAND_ORDER: tuple[HorizonBand, ...] = ("short", "medium", "long")
_DIRECTIONAL = {"bullish", "bearish"}


@dataclass(frozen=True)
class HorizonDecisionAssessment:
    direction: Direction
    structural_direction: Direction
    structural_score: float
    strength: float
    confidence: float
    volatility_risk: float
    manipulation_risk: float
    urgency: float
    risk_level: RiskLevel
    action_posture: ActionPosture
    alignment_status: HorizonAlignmentStatus
    conflict_type: HorizonConflictType
    conflict_score: float
    band_decisions: list[HorizonBandDecision]
    risk_breakdown: dict[str, RiskLevel]
    explanation: str


@dataclass(frozen=True)
class HorizonDecisionPolicy:
    formula_version: str = HORIZON_DECISION_FORMULA_VERSION
    short_band_max_ms: int = SHORT_BAND_MAX_MS
    long_band_min_ms: int = LONG_BAND_MIN_MS
    band_authority: Mapping[HorizonBand, float] = field(
        default_factory=lambda: dict(DEFAULT_BAND_AUTHORITY)
    )
    minimum_direction_score: float = 12
    minimum_direction_strength: float = 15
    minimum_direction_confidence: float = 45
    volatility_thresholds: RiskThresholds = RiskThresholds(
        medium=35,
        high=55,
        extreme=75,
    )
    manipulation_thresholds: RiskThresholds = RiskThresholds(
        medium=25,
        high=35,
        extreme=65,
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.formula_version, str)
            or not self.formula_version.strip()
        ):
            raise ValueError("horizon decision formula version is required")
        if (
            not isinstance(self.short_band_max_ms, int)
            or not isinstance(self.long_band_min_ms, int)
            or not 0 < self.short_band_max_ms < self.long_band_min_ms
        ):
            raise ValueError("horizon band boundaries must be positive and ordered")
        if (
            not isinstance(self.band_authority, Mapping)
            or set(self.band_authority) != set(_BAND_ORDER)
        ):
            raise ValueError("horizon band authority must cover all bands")
        if any(
            not isinstance(weight, (int, float))
            or not math.isfinite(weight)
            or weight <= 0
            for weight in self.band_authority.values()
        ):
            raise ValueError("horizon band authority weights must be positive")
        for value in (
            self.minimum_direction_score,
            self.minimum_direction_strength,
            self.minimum_direction_confidence,
        ):
            if (
                not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 100
            ):
                raise ValueError("horizon decision thresholds must be within bounds")
        for thresholds in (
            self.volatility_thresholds,
            self.manipulation_thresholds,
        ):
            values = (
                thresholds.medium,
                thresholds.high,
                thresholds.extreme,
            )
            if not (
                all(
                    isinstance(value, (int, float))
                    and math.isfinite(value)
                    for value in values
                )
                and 0
                <= thresholds.medium
                < thresholds.high
                < thresholds.extreme
                <= 100
            ):
                raise ValueError("horizon risk thresholds must be ordered")

    def identity_payload(self) -> dict[str, object]:
        return {
            "formula_version": self.formula_version,
            "short_band_max_ms": self.short_band_max_ms,
            "long_band_min_ms": self.long_band_min_ms,
            "band_authority": {
                band: float(self.band_authority[band])
                for band in _BAND_ORDER
            },
            "minimum_direction_score": float(self.minimum_direction_score),
            "minimum_direction_strength": float(
                self.minimum_direction_strength
            ),
            "minimum_direction_confidence": float(
                self.minimum_direction_confidence
            ),
            "volatility_thresholds": {
                "medium": float(self.volatility_thresholds.medium),
                "high": float(self.volatility_thresholds.high),
                "extreme": float(self.volatility_thresholds.extreme),
            },
            "manipulation_thresholds": {
                "medium": float(self.manipulation_thresholds.medium),
                "high": float(self.manipulation_thresholds.high),
                "extreme": float(self.manipulation_thresholds.extreme),
            },
        }

    def evaluate(
        self,
        horizon_signals: Iterable[HorizonSignal],
    ) -> HorizonDecisionAssessment:
        signals = list(horizon_signals)
        self._validate_signals(signals)
        grouped = self._group_signals(signals)
        band_decisions = [
            self._evaluate_band(band, grouped[band])
            for band in _BAND_ORDER
            if grouped[band]
        ]
        directional_bands = {
            item.band: item.direction
            for item in band_decisions
            if item.direction in _DIRECTIONAL
        }
        distinct_directions = set(directional_bands.values())
        has_band_conflict = any(
            item.direction == "conflict" for item in band_decisions
        )

        if len(distinct_directions) > 1 or has_band_conflict:
            direction: Direction = "conflict"
            alignment_status: HorizonAlignmentStatus = "conflicted"
            conflict_type = self._conflict_type(
                directional_bands,
                has_band_conflict=has_band_conflict,
            )
        elif distinct_directions:
            direction = next(iter(distinct_directions))
            alignment_status = (
                "aligned"
                if (
                    len(directional_bands) >= 2
                    and len(directional_bands) == len(band_decisions)
                )
                else "partial"
            )
            conflict_type = "none"
        else:
            direction = "neutral"
            alignment_status = "indeterminate"
            conflict_type = "none"

        structural_direction = self._structural_direction(band_decisions)
        band_weights = self._normalized_band_weights(band_decisions)
        structural_score = _round(
            sum(
                item.structural_score * band_weights[item.band]
                for item in band_decisions
            )
        )
        cross_conflict_score = self._cross_conflict_score(
            band_decisions,
            band_weights,
        )
        conflict_score = (
            _round(
                max(
                    cross_conflict_score,
                    max(
                        (item.conflict_score for item in band_decisions),
                        default=0,
                    ),
                )
            )
            if alignment_status == "conflicted"
            else 0.0
        )
        strength = self._overall_strength(
            direction,
            structural_score,
            conflict_score,
        )
        confidence = self._overall_confidence(
            band_decisions,
            band_weights,
            alignment_status,
            conflict_score,
        )
        volatility_risk = max(item.volatility_risk for item in signals)
        manipulation_risk = max(item.manipulation_risk for item in signals)
        risk_breakdown = {
            "volatility_risk": self.volatility_thresholds.level_for(
                volatility_risk
            ),
            "manipulation_risk": self.manipulation_thresholds.level_for(
                manipulation_risk
            ),
        }
        risk_level = max(
            risk_breakdown.values(),
            key=lambda level: RISK_LEVEL_RANK[level],
        )
        action_posture = self._action_posture(
            direction,
            alignment_status,
            risk_level,
        )
        urgency = _round(
            clamp(
                max(
                    volatility_risk,
                    manipulation_risk,
                    strength,
                    conflict_score,
                )
            )
        )
        explanation = self._explanation(
            direction=direction,
            structural_direction=structural_direction,
            alignment_status=alignment_status,
            conflict_type=conflict_type,
            risk_level=risk_level,
            action_posture=action_posture,
        )
        return HorizonDecisionAssessment(
            direction=direction,
            structural_direction=structural_direction,
            structural_score=structural_score,
            strength=strength,
            confidence=confidence,
            volatility_risk=_round(volatility_risk),
            manipulation_risk=_round(manipulation_risk),
            urgency=urgency,
            risk_level=risk_level,
            action_posture=action_posture,
            alignment_status=alignment_status,
            conflict_type=conflict_type,
            conflict_score=conflict_score,
            band_decisions=band_decisions,
            risk_breakdown=risk_breakdown,
            explanation=explanation,
        )

    def signal_weights(
        self,
        horizon_signals: Iterable[HorizonSignal],
    ) -> dict[str, float]:
        signals = list(horizon_signals)
        self._validate_signals(signals)
        grouped = self._group_signals(signals)
        present_bands = [band for band in _BAND_ORDER if grouped[band]]
        total_band_authority = sum(
            self.band_authority[band] for band in present_bands
        )
        weights: dict[str, float] = {}
        for band in present_bands:
            within_band = self._within_band_weights(grouped[band])
            band_weight = self.band_authority[band] / total_band_authority
            for signal in grouped[band]:
                weights[signal.horizon] = _round(
                    band_weight * within_band[signal.horizon],
                    digits=8,
                )
        return weights

    def band_for(self, horizon: str) -> HorizonBand:
        duration_ms = interval_to_millis(horizon)
        if duration_ms <= 0:
            raise ValueError("horizon must use a canonical interval")
        if duration_ms < self.short_band_max_ms:
            return "short"
        if duration_ms < self.long_band_min_ms:
            return "medium"
        return "long"

    def _validate_signals(self, signals: list[HorizonSignal]) -> None:
        if not 2 <= len(signals) <= 8:
            raise ValueError("horizon decision requires 2 to 8 signals")
        horizons = [item.horizon for item in signals]
        if len(horizons) != len(set(horizons)):
            raise ValueError("horizon decision signals must be unique")
        durations = [item.duration_ms for item in signals]
        if any(
            current <= previous
            for previous, current in zip(durations, durations[1:])
        ):
            raise ValueError(
                "horizon decision signals must be ordered short to long"
            )

    def _group_signals(
        self,
        signals: list[HorizonSignal],
    ) -> dict[HorizonBand, list[HorizonSignal]]:
        grouped: dict[HorizonBand, list[HorizonSignal]] = {
            "short": [],
            "medium": [],
            "long": [],
        }
        for signal in signals:
            grouped[self.band_for(signal.horizon)].append(signal)
        return grouped

    def _evaluate_band(
        self,
        band: HorizonBand,
        signals: list[HorizonSignal],
    ) -> HorizonBandDecision:
        weights = self._within_band_weights(signals)
        qualified = [item for item in signals if self._is_qualified(item)]
        scoring_signals = qualified or signals
        scoring_weight_total = sum(
            weights[item.horizon] for item in scoring_signals
        )
        structural_score = _round(
            sum(
                item.score * weights[item.horizon]
                for item in scoring_signals
            )
            / scoring_weight_total
        )
        qualified_directions = {item.direction for item in qualified}
        anchor = signals[-1]
        anchor_conflicted = self._is_material_conflict(anchor)

        if len(qualified_directions) > 1 or anchor_conflicted:
            direction: Direction = "conflict"
            alignment_status: HorizonAlignmentStatus = "conflicted"
        elif qualified_directions:
            direction = next(iter(qualified_directions))
            all_members_confirm = (
                len(qualified) == len(signals)
                and len(signals) >= 2
                and not any(self._is_material_conflict(item) for item in signals)
            )
            alignment_status = "aligned" if all_members_confirm else "partial"
        elif any(self._is_material_conflict(item) for item in signals):
            direction = "conflict"
            alignment_status = "conflicted"
        else:
            direction = "neutral"
            alignment_status = "indeterminate"

        conflict_score = (
            self._band_conflict_score(signals, weights)
            if alignment_status == "conflicted"
            else 0.0
        )
        if direction in _DIRECTIONAL:
            strength = _round(clamp(abs(structural_score) * 1.7))
        elif direction == "conflict":
            strength = _round(clamp(max(abs(structural_score), conflict_score)))
        else:
            strength = _round(clamp(abs(structural_score)))
        base_confidence = sum(
            item.confidence * weights[item.horizon] for item in signals
        )
        if alignment_status == "aligned":
            confidence_factor = 1.0
        elif alignment_status == "partial":
            confidence_factor = 0.8
        elif alignment_status == "conflicted":
            confidence_factor = 0.8 + 0.2 * conflict_score / 100
        else:
            confidence_factor = 0.65
        confidence = _round(clamp(base_confidence * confidence_factor))
        volatility_risk = max(item.volatility_risk for item in signals)
        manipulation_risk = max(item.manipulation_risk for item in signals)
        risk_level = max(
            self.volatility_thresholds.level_for(volatility_risk),
            self.manipulation_thresholds.level_for(manipulation_risk),
            key=lambda level: RISK_LEVEL_RANK[level],
        )
        return HorizonBandDecision(
            band=band,
            horizons=[item.horizon for item in signals],
            qualified_horizons=[item.horizon for item in qualified],
            anchor_horizon=anchor.horizon,
            direction=direction,
            structural_score=structural_score,
            strength=strength,
            confidence=confidence,
            volatility_risk=_round(volatility_risk),
            manipulation_risk=_round(manipulation_risk),
            risk_level=risk_level,
            alignment_status=alignment_status,
            conflict_score=_round(conflict_score),
        )

    def _within_band_weights(
        self,
        signals: list[HorizonSignal],
    ) -> dict[str, float]:
        raw_weights = [2**index for index in range(len(signals))]
        total = sum(raw_weights)
        return {
            signal.horizon: weight / total
            for signal, weight in zip(signals, raw_weights)
        }

    def _normalized_band_weights(
        self,
        band_decisions: list[HorizonBandDecision],
    ) -> dict[HorizonBand, float]:
        total = sum(self.band_authority[item.band] for item in band_decisions)
        return {
            item.band: self.band_authority[item.band] / total
            for item in band_decisions
        }

    def _is_qualified(self, signal: HorizonSignal) -> bool:
        return (
            signal.direction in _DIRECTIONAL
            and abs(signal.score) >= self.minimum_direction_score
            and signal.strength >= self.minimum_direction_strength
            and signal.confidence >= self.minimum_direction_confidence
        )

    def _is_material_conflict(self, signal: HorizonSignal) -> bool:
        return (
            signal.direction == "conflict"
            and signal.strength >= self.minimum_direction_strength
            and signal.confidence >= self.minimum_direction_confidence
        )

    def _band_conflict_score(
        self,
        signals: list[HorizonSignal],
        weights: Mapping[str, float],
    ) -> float:
        bullish_support = sum(
            abs(item.score) * weights[item.horizon]
            for item in signals
            if self._is_qualified(item) and item.direction == "bullish"
        )
        bearish_support = sum(
            abs(item.score) * weights[item.horizon]
            for item in signals
            if self._is_qualified(item) and item.direction == "bearish"
        )
        directional_total = bullish_support + bearish_support
        opposition_score = (
            200 * min(bullish_support, bearish_support) / directional_total
            if bullish_support > 0 and bearish_support > 0
            else 0
        )
        explicit_conflict_score = max(
            (
                item.strength * item.confidence / 100
                for item in signals
                if self._is_material_conflict(item)
            ),
            default=0,
        )
        return _round(clamp(max(opposition_score, explicit_conflict_score)))

    def _structural_direction(
        self,
        band_decisions: list[HorizonBandDecision],
    ) -> Direction:
        for item in reversed(band_decisions):
            if item.direction == "conflict":
                return "neutral"
            if item.direction in _DIRECTIONAL:
                return item.direction
        return "neutral"

    def _conflict_type(
        self,
        directional_bands: Mapping[HorizonBand, Direction],
        *,
        has_band_conflict: bool,
    ) -> HorizonConflictType:
        directions = set(directional_bands.values())
        if len(directions) <= 1:
            return "intra_band" if has_band_conflict else "none"
        if has_band_conflict:
            return "broad"

        long_direction = directional_bands.get("long")
        medium_direction = directional_bands.get("medium")
        short_direction = directional_bands.get("short")
        if long_direction is not None:
            lower_opposition = [
                band
                for band in ("short", "medium")
                if directional_bands.get(band) is not None
                and directional_bands[band] != long_direction
            ]
            if lower_opposition == ["short", "medium"]:
                return "lower_vs_long"
            if "medium" in lower_opposition:
                if short_direction == medium_direction:
                    return "lower_vs_long"
                return "medium_vs_long"
            if "short" in lower_opposition:
                return "short_vs_higher"
        if (
            medium_direction is not None
            and short_direction is not None
            and medium_direction != short_direction
        ):
            return "short_vs_higher"
        return "broad"

    def _cross_conflict_score(
        self,
        band_decisions: list[HorizonBandDecision],
        band_weights: Mapping[HorizonBand, float],
    ) -> float:
        bullish_support = sum(
            band_weights[item.band] * max(abs(item.structural_score), 1)
            for item in band_decisions
            if item.direction == "bullish"
        )
        bearish_support = sum(
            band_weights[item.band] * max(abs(item.structural_score), 1)
            for item in band_decisions
            if item.direction == "bearish"
        )
        total = bullish_support + bearish_support
        if bullish_support <= 0 or bearish_support <= 0:
            return 0.0
        return _round(clamp(200 * min(bullish_support, bearish_support) / total))

    def _overall_strength(
        self,
        direction: Direction,
        structural_score: float,
        conflict_score: float,
    ) -> float:
        if direction in _DIRECTIONAL:
            return _round(clamp(abs(structural_score) * 1.7))
        if direction == "conflict":
            return _round(clamp(max(abs(structural_score), conflict_score)))
        return _round(clamp(abs(structural_score)))

    def _overall_confidence(
        self,
        band_decisions: list[HorizonBandDecision],
        band_weights: Mapping[HorizonBand, float],
        alignment_status: HorizonAlignmentStatus,
        conflict_score: float,
    ) -> float:
        base_confidence = sum(
            item.confidence * band_weights[item.band]
            for item in band_decisions
        )
        coverage_factor = {1: 0.65, 2: 0.85, 3: 1.0}[
            len(band_decisions)
        ]
        conclusion_factor = {
            "aligned": 1.0,
            "partial": 0.85,
            "indeterminate": 0.65,
            "conflicted": 0.8 + 0.2 * conflict_score / 100,
        }[alignment_status]
        return _round(
            clamp(base_confidence * coverage_factor * conclusion_factor)
        )

    def _action_posture(
        self,
        direction: Direction,
        alignment_status: HorizonAlignmentStatus,
        risk_level: RiskLevel,
    ) -> ActionPosture:
        if risk_level == "extreme":
            return "avoid_chasing"
        if risk_level == "high":
            return "reduce_exposure"
        if risk_level == "medium":
            return "wait_for_confirmation"
        if alignment_status == "conflicted":
            return "wait_for_confirmation"
        if alignment_status == "indeterminate":
            return "observe"
        if direction in _DIRECTIONAL:
            return "cautious_follow"
        return "observe"

    def _explanation(
        self,
        *,
        direction: Direction,
        structural_direction: Direction,
        alignment_status: HorizonAlignmentStatus,
        conflict_type: HorizonConflictType,
        risk_level: RiskLevel,
        action_posture: ActionPosture,
    ) -> str:
        if alignment_status == "aligned":
            alignment_text = (
                "多个周期层级方向一致偏多"
                if direction == "bullish"
                else "多个周期层级方向一致偏空"
            )
        elif alignment_status == "partial":
            alignment_text = (
                "当前只有部分周期层级形成有效方向，确认覆盖仍不足"
            )
        elif alignment_status == "indeterminate":
            alignment_text = "各周期尚未形成足够可靠的方向证据"
        else:
            conflict_text = {
                "intra_band": "同一周期层级内部存在方向冲突",
                "short_vs_higher": "短周期与更高周期结构冲突，方向相反",
                "medium_vs_long": "中周期与长周期结构冲突，方向相反",
                "lower_vs_long": "短中周期共同逆向于长周期，形成结构冲突",
                "broad": "多个周期层级存在广泛方向冲突",
                "none": "多周期方向存在冲突",
            }[conflict_type]
            alignment_text = conflict_text

        structural_text = {
            "bullish": "较高周期结构偏多",
            "bearish": "较高周期结构偏空",
            "neutral": "较高周期结构尚不明确",
            "conflict": "较高周期结构存在冲突",
        }[structural_direction]
        risk_text = {
            "low": "风险水平较低",
            "medium": "风险水平中等",
            "high": "风险水平偏高",
            "extreme": "风险水平极高",
        }[risk_level]
        action_text = {
            "observe": "更适合继续观察",
            "wait_for_confirmation": "更适合等待跨周期确认",
            "cautious_follow": "可以谨慎关注顺结构机会",
            "reduce_exposure": "应优先降低风险暴露",
            "avoid_chasing": "不适合追逐当前波动",
        }[action_posture]
        return (
            f"{alignment_text}；{structural_text}。{risk_text}，{action_text}。"
        )


def _round(value: float, *, digits: int = 3) -> float:
    return round(float(value), digits)
