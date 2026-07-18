from market_cell.cells.base import MarketCell
from market_cell.cells.volume_price_anomaly import (
    KNOWN_ANOMALY_STATES,
    VolumePriceAnomalyCell,
)
from market_cell.features import FEATURE_VERSION, build_feature_snapshot
from market_cell.models import AnalysisRequest, CellResult, Evidence
from market_cell.scoring import clamp, score


ANOMALY_CELL_ID = VolumePriceAnomalyCell.cell_id
ANOMALY_FORMULA_VERSION = VolumePriceAnomalyCell.formula_version
MINIMUM_SHAPE_CANDLE_COUNT = 4


class ManipulationRiskCell(MarketCell):
    cell_id = "risk.manipulation"
    name = "ManipulationRiskCell"
    category = "risk"
    description = (
        "聚合稳健量价异常与大振幅、长影线形态，估计市场完整性风险，"
        "不对真实操纵意图作确定性判断。"
    )
    formula_version = "shape_anomaly_manipulation_risk_v0.3"
    inputs = [
        "candles.open",
        "candles.high",
        "candles.low",
        "candles.close",
        "child_results.risk.volume_price_anomaly",
    ]
    outputs = [
        "manipulation_risk",
        "volatility_risk",
        "urgency",
        "anomaly_state",
        "range_component",
        "wick_component",
    ]
    risk_dimensions = ["manipulation_risk", "volatility_risk"]

    def analyze(
        self,
        request: AnalysisRequest,
        child_results: list[CellResult] | None = None,
    ) -> CellResult:
        anomaly = _required_anomaly_result(child_results)
        if anomaly.target != request.target or anomaly.horizon != request.horizon:
            raise ValueError(
                "ManipulationRiskCell anomaly result target/horizon does not "
                "match request"
            )
        anomaly_formula_version = anomaly.metadata.get("formula_version")
        if anomaly_formula_version != ANOMALY_FORMULA_VERSION:
            raise ValueError(
                "ManipulationRiskCell requires volume/price anomaly formula "
                f"{ANOMALY_FORMULA_VERSION}"
            )
        anomaly_state = str(anomaly.metadata.get("anomaly_state", ""))
        if anomaly_state not in KNOWN_ANOMALY_STATES:
            raise ValueError(
                f"ManipulationRiskCell received unknown anomaly state "
                f"{anomaly_state!r}"
            )

        features = build_feature_snapshot(request.candles)
        shape_history_sufficient = (
            len(request.candles) >= MINIMUM_SHAPE_CANDLE_COUNT
        )
        latest_range = features.latest_range_pct
        wick_ratio = features.latest_wick_ratio
        range_component = 0.0
        wick_component = 0.0
        local_evidence: list[Evidence] = []

        if shape_history_sufficient and latest_range > 4.0:
            range_component = clamp((latest_range - 4.0) * 8, maximum=30)
            local_evidence.append(
                Evidence(
                    source="large_intraperiod_range",
                    summary=(
                        f"最新 K 线振幅 {latest_range:.2f}%，"
                        "短周期波动显著放大。"
                    ),
                )
            )

        if shape_history_sufficient and wick_ratio > 0.55:
            wick_component = clamp((wick_ratio - 0.55) * 60, maximum=25)
            local_evidence.append(
                Evidence(
                    source="long_wick",
                    summary=(
                        f"最新 K 线影线占比 {wick_ratio:.2f}，"
                        "存在快速拉回或价格拒绝形态。"
                    ),
                )
            )

        anomaly_component = anomaly.manipulation_risk
        range_component_weight = (
            0.5 if anomaly.metadata.get("price_anomalous") else 1.0
        )
        manipulation_risk = clamp(
            anomaly_component
            + range_component * range_component_weight
            + wick_component
        )
        volatility_risk = clamp(
            max(
                anomaly.volatility_risk,
                latest_range * 14 if shape_history_sufficient else 0,
            )
        )
        direction = "conflict" if manipulation_risk >= 35 else "neutral"
        confidence = _confidence(
            anomaly_confidence=anomaly.confidence,
            shape_history_sufficient=shape_history_sufficient,
            local_evidence_count=len(local_evidence),
        )
        evidence = [
            Evidence(
                source=anomaly.cell_id,
                summary=(
                    f"state={anomaly_state}, "
                    f"anomaly_strength={anomaly.strength:.1f}, "
                    f"manipulation_risk={anomaly.manipulation_risk:.1f}"
                ),
                reliability=anomaly.confidence,
            ),
            *local_evidence,
        ]
        if not shape_history_sufficient:
            evidence.append(
                Evidence(
                    source="candles.shape_history",
                    summary=(
                        f"candle_count={len(request.candles)}, "
                        f"minimum={MINIMUM_SHAPE_CANDLE_COUNT}; "
                        "shape components skipped"
                    ),
                    reliability=20,
                )
            )

        return CellResult(
            cell_id=self.cell_id,
            name=self.name,
            category=self.category,
            target=request.target,
            horizon=request.horizon,
            direction=direction,
            strength=round(manipulation_risk, 4),
            confidence=confidence,
            volatility_risk=round(volatility_risk, 4),
            manipulation_risk=round(manipulation_risk, 4),
            urgency=round(max(manipulation_risk, volatility_risk), 4),
            score=score(direction, manipulation_risk, confidence),
            explanation=(
                f"量价异常状态为 {anomaly_state}，结合最新振幅和影线后，"
                f"市场完整性风险估计为 {manipulation_risk:.1f}/100。"
                "该结果描述异常风险，不证明存在操纵行为。"
            ),
            evidence=evidence,
            children=[anomaly],
            metadata={
                "formula_version": self.formula_version,
                "anomaly_cell_id": ANOMALY_CELL_ID,
                "anomaly_formula_version": ANOMALY_FORMULA_VERSION,
                "anomaly_state": anomaly_state,
                "anomaly_component": round(anomaly_component, 4),
                "latest_range_pct": round(latest_range, 4),
                "range_component": round(range_component, 4),
                "range_component_weight": range_component_weight,
                "wick_ratio": round(wick_ratio, 4),
                "wick_component": round(wick_component, 4),
                "shape_history_sufficient": shape_history_sufficient,
                "minimum_shape_candle_count": MINIMUM_SHAPE_CANDLE_COUNT,
                "feature_version": FEATURE_VERSION,
                "manipulation_inference": "risk_pattern_not_proof",
            },
        )


def _required_anomaly_result(
    child_results: list[CellResult] | None,
) -> CellResult:
    children = list(child_results or [])
    matches = [item for item in children if item.cell_id == ANOMALY_CELL_ID]
    if len(children) != 1 or len(matches) != 1:
        raise ValueError(
            "ManipulationRiskCell requires exactly one "
            f"{ANOMALY_CELL_ID} child result"
        )
    return matches[0]


def _confidence(
    *,
    anomaly_confidence: float,
    shape_history_sufficient: bool,
    local_evidence_count: int,
) -> float:
    value = (
        anomaly_confidence * 0.55
        + 30
        + (10 if shape_history_sufficient else 0)
        + local_evidence_count * 8
    )
    return round(clamp(value, maximum=90), 4)
