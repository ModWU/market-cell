from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import re
from typing import Any, Literal

from market_cell.data.timeframes import interval_to_millis
from market_cell.hashing import stable_json_hash
from market_cell.models import (
    ActionPosture,
    Direction,
    Evidence,
    RiskLevel,
)


HORIZON_DECISION_SCHEMA_VERSION = "horizon_decision.v1"

HorizonBand = Literal["short", "medium", "long"]
HorizonAlignmentStatus = Literal[
    "aligned",
    "partial",
    "conflicted",
    "indeterminate",
]
HorizonConflictType = Literal[
    "none",
    "intra_band",
    "short_vs_higher",
    "medium_vs_long",
    "lower_vs_long",
    "broad",
]

_BAND_ORDER: dict[HorizonBand, int] = {
    "short": 0,
    "medium": 1,
    "long": 2,
}
_BATCH_ID_PATTERN = re.compile(r"^multi-horizon:[a-f0-9]{32}$")
_DECISION_ID_PATTERN = re.compile(r"^horizon-decision:[a-f0-9]{24}$")
_REQUEST_ID_PATTERN = re.compile(
    r"^multi-horizon-request:[a-f0-9]{24}$"
)
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_DIRECTIONS = {"bullish", "bearish", "neutral", "conflict"}
_STRUCTURAL_DIRECTIONS = {"bullish", "bearish", "neutral"}
_ALIGNMENT_STATUSES = {
    "aligned",
    "partial",
    "conflicted",
    "indeterminate",
}
_CONFLICT_TYPES = {
    "none",
    "intra_band",
    "short_vs_higher",
    "medium_vs_long",
    "lower_vs_long",
    "broad",
}
_RISK_LEVELS = {"low", "medium", "high", "extreme"}
_RISK_LEVEL_RANK = {"low": 0, "medium": 1, "high": 2, "extreme": 3}
_ACTION_POSTURES = {
    "observe",
    "wait_for_confirmation",
    "cautious_follow",
    "reduce_exposure",
    "avoid_chasing",
}


@dataclass(frozen=True)
class HorizonSignal:
    horizon: str
    direction: Direction
    score: float
    strength: float
    confidence: float
    volatility_risk: float
    manipulation_risk: float

    def __post_init__(self) -> None:
        duration_ms = interval_to_millis(self.horizon)
        if duration_ms <= 0:
            raise ValueError("horizon signal must use a canonical horizon")
        if self.direction not in _DIRECTIONS:
            raise ValueError("horizon signal direction is invalid")
        for name, value, minimum, maximum in (
            ("score", self.score, -100, 100),
            ("strength", self.strength, 0, 100),
            ("confidence", self.confidence, 0, 100),
            ("volatility_risk", self.volatility_risk, 0, 100),
            ("manipulation_risk", self.manipulation_risk, 0, 100),
        ):
            if (
                not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not minimum <= value <= maximum
            ):
                raise ValueError(
                    f"horizon signal {name} must be finite and within bounds"
                )
            object.__setattr__(self, name, float(value))
        if self.direction == "bullish" and self.score <= 0:
            raise ValueError("bullish horizon signal must have positive score")
        if self.direction == "bearish" and self.score >= 0:
            raise ValueError("bearish horizon signal must have negative score")

    @property
    def duration_ms(self) -> int:
        return interval_to_millis(self.horizon)

    def identity_payload(self) -> dict[str, object]:
        return {
            "horizon": self.horizon,
            "direction": self.direction,
            "score": float(self.score),
            "strength": float(self.strength),
            "confidence": float(self.confidence),
            "volatility_risk": float(self.volatility_risk),
            "manipulation_risk": float(self.manipulation_risk),
        }


@dataclass(frozen=True)
class HorizonBandDecision:
    band: HorizonBand
    horizons: list[str]
    qualified_horizons: list[str]
    anchor_horizon: str
    direction: Direction
    structural_score: float
    strength: float
    confidence: float
    volatility_risk: float
    manipulation_risk: float
    risk_level: RiskLevel
    alignment_status: HorizonAlignmentStatus
    conflict_score: float

    def __post_init__(self) -> None:
        if self.band not in _BAND_ORDER:
            raise ValueError("unknown horizon band")
        if not self.horizons or len(self.horizons) != len(set(self.horizons)):
            raise ValueError("horizon band members must be non-empty and unique")
        durations = [interval_to_millis(item) for item in self.horizons]
        if any(
            current <= previous
            for previous, current in zip(durations, durations[1:])
        ):
            raise ValueError("horizon band members must be ordered short to long")
        if self.anchor_horizon != self.horizons[-1]:
            raise ValueError("horizon band anchor must be its longest horizon")
        if len(self.qualified_horizons) != len(set(self.qualified_horizons)):
            raise ValueError("qualified horizons must be unique")
        if any(item not in self.horizons for item in self.qualified_horizons):
            raise ValueError("qualified horizons must belong to their band")
        if self.qualified_horizons != [
            item for item in self.horizons if item in self.qualified_horizons
        ]:
            raise ValueError("qualified horizons must preserve source order")
        if self.direction not in _DIRECTIONS:
            raise ValueError("unknown horizon band direction")
        if self.alignment_status not in _ALIGNMENT_STATUSES:
            raise ValueError("unknown horizon band alignment status")
        if self.risk_level not in _RISK_LEVELS:
            raise ValueError("unknown horizon band risk level")
        _validate_score(self.structural_score, "structural_score")
        for name in (
            "strength",
            "confidence",
            "volatility_risk",
            "manipulation_risk",
            "conflict_score",
        ):
            _validate_percentage(getattr(self, name), name)
        if self.alignment_status == "conflicted":
            if self.direction != "conflict" or self.conflict_score <= 0:
                raise ValueError(
                    "conflicted horizon band must expose conflict direction and score"
                )
        elif self.direction == "conflict" or self.conflict_score != 0:
            raise ValueError(
                "non-conflicted horizon band cannot expose conflict state"
            )
        if self.alignment_status == "indeterminate" and self.direction != "neutral":
            raise ValueError(
                "indeterminate horizon band must remain neutral"
            )
        if self.alignment_status in {"aligned", "partial"} and self.direction not in {
            "bullish",
            "bearish",
        }:
            raise ValueError(
                "aligned or partial horizon band must be directional"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HorizonDecision:
    decision_id: str
    decision_hash: str
    source_batch_id: str
    request_id: str
    request_hash: str
    target: str
    as_of_ms: int
    horizon_order: list[str]
    source_signals: list[HorizonSignal]
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
    risk_breakdown: dict[str, RiskLevel]
    alignment_status: HorizonAlignmentStatus
    conflict_type: HorizonConflictType
    conflict_score: float
    band_decisions: list[HorizonBandDecision]
    evidence: list[Evidence]
    explanation: str
    source_graph_id: str
    source_graph_version: str
    source_graph_content_hash: str
    source_formula_versions: dict[str, str]
    policy: dict[str, Any]
    formula_version: str
    created_at: str
    source_schema_version: str = "multi_horizon_analysis.v1"
    schema_version: str = HORIZON_DECISION_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)
    disclaimer: str = (
        "MarketCell 多周期判断只提供结构化分析和风险提示，"
        "不构成投资建议。"
    )

    def __post_init__(self) -> None:
        if _SHA256_PATTERN.fullmatch(self.decision_hash) is None:
            raise ValueError("horizon decision hash must be SHA-256")
        if _DECISION_ID_PATTERN.fullmatch(self.decision_id) is None:
            raise ValueError("horizon decision id must use the canonical id")
        if self.decision_id != f"horizon-decision:{self.decision_hash[:24]}":
            raise ValueError("horizon decision id must match decision hash")
        if _BATCH_ID_PATTERN.fullmatch(self.source_batch_id) is None:
            raise ValueError("horizon decision source batch id is invalid")
        if _SHA256_PATTERN.fullmatch(self.request_hash) is None:
            raise ValueError("horizon decision request hash must be SHA-256")
        if _REQUEST_ID_PATTERN.fullmatch(self.request_id) is None:
            raise ValueError("horizon decision request id is invalid")
        if self.request_id != (
            f"multi-horizon-request:{self.request_hash[:24]}"
        ):
            raise ValueError("horizon decision request id must match request hash")
        if not self.target.strip() or self.target != self.target.strip():
            raise ValueError("horizon decision target must be canonical")
        if self.as_of_ms < 0:
            raise ValueError("horizon decision as_of_ms must not be negative")
        if not 2 <= len(self.horizon_order) <= 8:
            raise ValueError("horizon decision requires 2 to 8 horizons")
        if len(self.horizon_order) != len(set(self.horizon_order)):
            raise ValueError("horizon decision horizons must be unique")
        if [item.horizon for item in self.source_signals] != self.horizon_order:
            raise ValueError(
                "horizon decision source signals must match horizon order"
            )
        if self.direction not in _DIRECTIONS:
            raise ValueError("unknown horizon decision direction")
        if self.structural_direction not in _STRUCTURAL_DIRECTIONS:
            raise ValueError("unknown structural horizon direction")
        if self.alignment_status not in _ALIGNMENT_STATUSES:
            raise ValueError("unknown horizon alignment status")
        if self.conflict_type not in _CONFLICT_TYPES:
            raise ValueError("unknown horizon conflict type")
        if self.risk_level not in _RISK_LEVELS:
            raise ValueError("unknown horizon decision risk level")
        if self.action_posture not in _ACTION_POSTURES:
            raise ValueError("unknown horizon action posture")
        if set(self.risk_breakdown) != {
            "volatility_risk",
            "manipulation_risk",
        } or any(
            level not in _RISK_LEVELS
            for level in self.risk_breakdown.values()
        ):
            raise ValueError("horizon decision risk breakdown is invalid")
        _validate_score(self.structural_score, "structural_score")
        for name in (
            "strength",
            "confidence",
            "volatility_risk",
            "manipulation_risk",
            "urgency",
            "conflict_score",
        ):
            _validate_percentage(getattr(self, name), name)
        if self.alignment_status == "conflicted":
            if (
                self.direction != "conflict"
                or self.conflict_type == "none"
                or self.conflict_score <= 0
            ):
                raise ValueError(
                    "conflicted horizon decision must expose conflict details"
                )
        elif (
            self.direction == "conflict"
            or self.conflict_type != "none"
            or self.conflict_score != 0
        ):
            raise ValueError(
                "non-conflicted horizon decision cannot expose conflict details"
            )
        if self.alignment_status == "indeterminate" and self.direction != "neutral":
            raise ValueError("indeterminate horizon decision must remain neutral")
        if self.alignment_status in {"aligned", "partial"} and self.direction not in {
            "bullish",
            "bearish",
        }:
            raise ValueError(
                "aligned or partial horizon decision must be directional"
            )
        if not self.band_decisions or len(self.band_decisions) > 3:
            raise ValueError("horizon decision must contain 1 to 3 band decisions")
        band_order = [_BAND_ORDER[item.band] for item in self.band_decisions]
        if band_order != sorted(set(band_order)):
            raise ValueError("horizon decision bands must be unique and ordered")
        covered_horizons = [
            horizon
            for band in self.band_decisions
            for horizon in band.horizons
        ]
        if covered_horizons != self.horizon_order:
            raise ValueError(
                "horizon decision bands must partition the source horizon order"
            )
        if len(self.evidence) != len(self.horizon_order):
            raise ValueError(
                "horizon decision must retain one evidence item per horizon"
            )
        if [item.source for item in self.evidence] != [
            f"horizon:{horizon}" for horizon in self.horizon_order
        ]:
            raise ValueError(
                "horizon decision evidence must preserve horizon order"
            )
        if any(
            not item.summary.strip()
            or not isinstance(item.weight, (int, float))
            or not math.isfinite(item.weight)
            or item.weight < 0
            for item in self.evidence
        ):
            raise ValueError("horizon decision evidence is invalid")
        if not math.isclose(
            sum(item.weight for item in self.evidence),
            1,
            abs_tol=1e-6,
        ):
            raise ValueError("horizon decision evidence weights must sum to one")
        for signal, evidence in zip(self.source_signals, self.evidence):
            _validate_percentage(evidence.freshness, "evidence freshness")
            _validate_percentage(evidence.reliability, "evidence reliability")
            if not math.isclose(
                evidence.reliability,
                signal.confidence,
                abs_tol=1e-6,
            ):
                raise ValueError(
                    "horizon decision evidence reliability must match source"
                )
        if not self.explanation.strip():
            raise ValueError("horizon decision explanation is required")
        if (
            not self.source_graph_id.strip()
            or not self.source_graph_version.strip()
        ):
            raise ValueError("horizon decision source graph identity is required")
        if _SHA256_PATTERN.fullmatch(self.source_graph_content_hash) is None:
            raise ValueError(
                "horizon decision source graph hash must be SHA-256"
            )
        if not self.source_formula_versions or any(
            not cell_id.strip() or not version.strip()
            for cell_id, version in self.source_formula_versions.items()
        ):
            raise ValueError(
                "horizon decision source formula versions must be complete"
            )
        if not self.formula_version.strip():
            raise ValueError("horizon decision formula version is required")
        _validate_policy(self.policy, self.formula_version)
        expected_volatility_risk = round(
            max(item.volatility_risk for item in self.source_signals),
            3,
        )
        expected_manipulation_risk = round(
            max(item.manipulation_risk for item in self.source_signals),
            3,
        )
        if not math.isclose(
            self.volatility_risk,
            expected_volatility_risk,
            abs_tol=1e-6,
        ) or not math.isclose(
            self.manipulation_risk,
            expected_manipulation_risk,
            abs_tol=1e-6,
        ):
            raise ValueError("horizon decision risks must preserve source maxima")
        expected_breakdown = {
            "volatility_risk": _risk_level_for(
                self.volatility_risk,
                self.policy["volatility_thresholds"],
            ),
            "manipulation_risk": _risk_level_for(
                self.manipulation_risk,
                self.policy["manipulation_thresholds"],
            ),
        }
        if self.risk_breakdown != expected_breakdown:
            raise ValueError("horizon decision risk breakdown has drifted")
        expected_risk_level = max(
            expected_breakdown.values(),
            key=lambda level: _RISK_LEVEL_RANK[level],
        )
        if self.risk_level != expected_risk_level:
            raise ValueError("horizon decision risk level has drifted")
        signal_by_horizon = {
            item.horizon: item for item in self.source_signals
        }
        for band in self.band_decisions:
            band_signals = [signal_by_horizon[item] for item in band.horizons]
            if not math.isclose(
                band.volatility_risk,
                round(max(item.volatility_risk for item in band_signals), 3),
                abs_tol=1e-6,
            ) or not math.isclose(
                band.manipulation_risk,
                round(
                    max(item.manipulation_risk for item in band_signals),
                    3,
                ),
                abs_tol=1e-6,
            ):
                raise ValueError("horizon band risks must preserve source maxima")
            expected_band_risk = max(
                _risk_level_for(
                    band.volatility_risk,
                    self.policy["volatility_thresholds"],
                ),
                _risk_level_for(
                    band.manipulation_risk,
                    self.policy["manipulation_thresholds"],
                ),
                key=lambda level: _RISK_LEVEL_RANK[level],
            )
            if band.risk_level != expected_band_risk:
                raise ValueError("horizon band risk level has drifted")
        if not self.created_at.strip():
            raise ValueError("horizon decision created_at is required")
        if self.source_schema_version != "multi_horizon_analysis.v1":
            raise ValueError("unsupported horizon decision source schema")
        if self.schema_version != HORIZON_DECISION_SCHEMA_VERSION:
            raise ValueError("unsupported horizon decision schema")
        if not self.disclaimer.strip():
            raise ValueError("horizon decision disclaimer is required")
        if stable_json_hash(self.identity_payload()) != self.decision_hash:
            raise ValueError(
                "horizon decision hash does not match canonical payload"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_schema_version": self.source_schema_version,
            "request_hash": self.request_hash,
            "target": self.target,
            "as_of_ms": self.as_of_ms,
            "horizon_order": list(self.horizon_order),
            "graph_id": self.source_graph_id,
            "graph_version": self.source_graph_version,
            "graph_content_hash": self.source_graph_content_hash,
            "source_formula_versions": dict(self.source_formula_versions),
            "signals": [
                item.identity_payload() for item in self.source_signals
            ],
            "policy": dict(self.policy),
            "decision": {
                "direction": self.direction,
                "structural_direction": self.structural_direction,
                "structural_score": self.structural_score,
                "strength": self.strength,
                "confidence": self.confidence,
                "volatility_risk": self.volatility_risk,
                "manipulation_risk": self.manipulation_risk,
                "urgency": self.urgency,
                "risk_level": self.risk_level,
                "action_posture": self.action_posture,
                "alignment_status": self.alignment_status,
                "conflict_type": self.conflict_type,
                "conflict_score": self.conflict_score,
                "band_decisions": [
                    item.to_dict() for item in self.band_decisions
                ],
                "risk_breakdown": dict(self.risk_breakdown),
            },
        }


def _validate_percentage(value: float, name: str) -> None:
    if (
        not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 100
    ):
        raise ValueError(f"horizon decision {name} must be within 0 and 100")


def _validate_score(value: float, name: str) -> None:
    if (
        not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not -100 <= value <= 100
    ):
        raise ValueError(f"horizon decision {name} must be within -100 and 100")


def _validate_policy(policy: dict[str, Any], formula_version: str) -> None:
    required = {
        "formula_version",
        "short_band_max_ms",
        "long_band_min_ms",
        "band_authority",
        "minimum_direction_score",
        "minimum_direction_strength",
        "minimum_direction_confidence",
        "volatility_thresholds",
        "manipulation_thresholds",
    }
    if set(policy) != required:
        raise ValueError("horizon decision policy fields are invalid")
    if policy["formula_version"] != formula_version:
        raise ValueError("horizon decision policy must match formula version")
    short_max = policy["short_band_max_ms"]
    long_min = policy["long_band_min_ms"]
    if (
        not isinstance(short_max, int)
        or not isinstance(long_min, int)
        or not 0 < short_max < long_min
    ):
        raise ValueError("horizon decision policy band boundaries are invalid")
    authority = policy["band_authority"]
    if not isinstance(authority, dict) or set(authority) != set(_BAND_ORDER):
        raise ValueError("horizon decision policy band authority is invalid")
    if any(
        not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
        for value in authority.values()
    ):
        raise ValueError("horizon decision policy band weights are invalid")
    for name in (
        "minimum_direction_score",
        "minimum_direction_strength",
        "minimum_direction_confidence",
    ):
        value = policy[name]
        if (
            not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 100
        ):
            raise ValueError("horizon decision policy threshold is invalid")
    for name in ("volatility_thresholds", "manipulation_thresholds"):
        thresholds = policy[name]
        if not isinstance(thresholds, dict) or set(thresholds) != {
            "medium",
            "high",
            "extreme",
        }:
            raise ValueError("horizon decision policy risk thresholds are invalid")
        medium = thresholds["medium"]
        high = thresholds["high"]
        extreme = thresholds["extreme"]
        if not all(
            isinstance(value, (int, float)) and math.isfinite(value)
            for value in (medium, high, extreme)
        ) or not 0 <= medium < high < extreme <= 100:
            raise ValueError("horizon decision policy risk thresholds are invalid")


def _risk_level_for(
    value: float,
    thresholds: dict[str, float],
) -> RiskLevel:
    if value >= thresholds["extreme"]:
        return "extreme"
    if value >= thresholds["high"]:
        return "high"
    if value >= thresholds["medium"]:
        return "medium"
    return "low"
