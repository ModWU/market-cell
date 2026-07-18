from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Direction = Literal["bullish", "bearish", "neutral", "conflict"]
RiskLevel = Literal["low", "medium", "high", "extreme"]
ActionPosture = Literal[
    "observe",
    "wait_for_confirmation",
    "cautious_follow",
    "reduce_exposure",
    "avoid_chasing",
]

REPORT_SCHEMA_VERSION = "analysis_report.v1"


@dataclass(frozen=True)
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Candle":
        return cls(
            timestamp=str(data.get("timestamp", "")),
            open=float(data["open"]),
            high=float(data["high"]),
            low=float(data["low"]),
            close=float(data["close"]),
            volume=float(data["volume"]),
        )


@dataclass(frozen=True)
class MarketEvent:
    title: str
    category: str
    sentiment: float
    impact: float
    freshness: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MarketEvent":
        return cls(
            title=str(data["title"]),
            category=str(data.get("category", "general")),
            sentiment=float(data.get("sentiment", 0)),
            impact=float(data.get("impact", 0)),
            freshness=float(data.get("freshness", 50)),
        )


@dataclass(frozen=True)
class Evidence:
    source: str
    summary: str
    weight: float = 1.0
    freshness: float = 100.0
    reliability: float = 70.0


@dataclass(frozen=True)
class CellManifest:
    cell_id: str
    name: str
    category: str
    description: str
    inputs: list[str]
    outputs: list[str]
    formula_version: str
    required_input_kinds: list[str] = field(
        default_factory=lambda: ["analysis_request"]
    )
    risk_dimensions: list[str] = field(default_factory=list)
    status: str = "experimental"


@dataclass(frozen=True)
class AnalysisRequest:
    target: str
    horizon: str
    candles: list[Candle]
    events: list[MarketEvent] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalysisRequest":
        candles = [Candle.from_dict(item) for item in data.get("candles", [])]
        events = [MarketEvent.from_dict(item) for item in data.get("events", [])]
        return cls(
            target=str(data["target"]),
            horizon=str(data.get("horizon", "1h")),
            candles=candles,
            events=events,
            context=dict(data.get("context", {})),
        )


@dataclass(frozen=True)
class CellResult:
    cell_id: str
    name: str
    category: str
    target: str
    horizon: str
    direction: Direction
    strength: float
    confidence: float
    volatility_risk: float
    manipulation_risk: float
    urgency: float
    score: float
    explanation: str
    risk_level: RiskLevel | None = None
    action_posture: ActionPosture | None = None
    evidence: list[Evidence] = field(default_factory=list)
    children: list["CellResult"] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AnalysisReport:
    target: str
    horizon: str
    decision: CellResult
    summary: str
    run_id: str | None = None
    report_id: str | None = None
    schema_version: str = REPORT_SCHEMA_VERSION
    engine_version: str | None = None
    formula_versions: dict[str, str] = field(default_factory=dict)
    created_at: str | None = None
    disclaimer: str = "MarketCell 只提供结构化分析和风险提示，不构成投资建议。"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
