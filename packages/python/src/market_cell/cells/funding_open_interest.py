from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from market_cell.cells.base import MarketCell
from market_cell.data import (
    FundingOpenInterestPoint,
    FundingOpenInterestSnapshot,
)
from market_cell.inputs import CellInputBundle, InputCompositionError
from market_cell.models import AnalysisRequest, CellResult, Evidence
from market_cell.scoring import clamp, score


MINIMUM_HISTORY_POINT_COUNT = 8
MAXIMUM_HISTORY_POINT_COUNT = 48
MINIMUM_CADENCE_COVERAGE = 0.80
CADENCE_TOLERANCE_RATIO = 0.25
MAX_ACCEPTABLE_FETCH_LATENCY_MS = 60_000
FUNDING_NORMALIZATION_HOURS = 8.0
FUNDING_CROWDING_THRESHOLD_BPS = 5.0
MINIMUM_FUNDING_SHIFT_BPS = 2.0
FUNDING_ROBUST_Z_THRESHOLD = 3.5
FUNDING_MAD_FLOOR_BPS = 0.5
OPEN_INTEREST_CHANGE_THRESHOLD_PCT = 2.5
OPEN_INTEREST_ROBUST_Z_THRESHOLD = 3.5
OPEN_INTEREST_MAD_FLOOR_PCT = 0.25
PRICE_DIRECTION_THRESHOLD_PCT = 0.5
SINGLE_WINDOW_CONFIDENCE_CAP = 88.0


KNOWN_POSITIONING_STATES = {
    "insufficient_history",
    "degraded_input",
    "normal",
    "positive_funding_crowding",
    "negative_funding_crowding",
    "funding_shift_up",
    "funding_shift_down",
    "leveraged_long_buildup",
    "leveraged_short_buildup",
    "crowded_long_buildup",
    "crowded_short_buildup",
    "long_liquidation",
    "short_covering",
    "open_interest_surge_without_price_confirmation",
    "deleveraging_without_price_confirmation",
}


@dataclass(frozen=True)
class _PositioningMetrics:
    latest_funding_8h_bps: float
    historical_funding_median_8h_bps: float
    funding_mad_8h_bps: float
    funding_scale_8h_bps: float
    funding_robust_z: float
    latest_open_interest_notional: float
    latest_open_interest_notional_change_pct: float
    latest_open_interest_base_equivalent: float
    latest_open_interest_exposure_change_pct: float
    historical_abs_oi_change_median_pct: float
    open_interest_mad_pct: float
    open_interest_scale_pct: float
    open_interest_robust_z: float
    latest_mark_price: float
    latest_mark_price_change_pct: float


class FundingOpenInterestCell(MarketCell):
    cell_id = "crypto.funding_open_interest"
    name = "FundingOpenInterestCell"
    category = "crypto_market"
    description = (
        "使用同步的资金费率、持仓名义价值和标记价格时间序列，"
        "识别杠杆建仓、去杠杆与资金费率拥挤风险。"
    )
    formula_version = "robust_funding_open_interest_positioning_v0.1"
    required_input_kinds = [
        "analysis_request",
        "funding_open_interest_snapshot",
    ]
    inputs = [
        "analysis_request.target",
        "analysis_request.horizon",
        "funding_open_interest_snapshot.points.funding_rate",
        "funding_open_interest_snapshot.points.open_interest_notional",
        "funding_open_interest_snapshot.points.mark_price",
        "funding_open_interest_snapshot.funding_interval_hours",
        "funding_open_interest_snapshot.funding_rate_type",
        "funding_open_interest_snapshot.sample_interval_ms",
        "funding_open_interest_snapshot.notional_currency",
        "funding_open_interest_snapshot.contract_type",
        "funding_open_interest_snapshot.provenance",
    ]
    outputs = [
        "direction",
        "strength",
        "confidence",
        "volatility_risk",
        "risk_assessment_status",
        "positioning_state",
        "latest_funding_8h_bps",
        "latest_open_interest_exposure_change_pct",
        "latest_mark_price_change_pct",
    ]
    risk_dimensions = ["volatility_risk"]
    status = "experimental"

    def analyze_inputs(
        self,
        inputs: CellInputBundle,
        child_results: list[CellResult] | None = None,
    ) -> CellResult:
        derivatives = FundingOpenInterestSnapshot.from_input_snapshot(
            inputs.require_one("funding_open_interest_snapshot")
        )
        return self._analyze_snapshot(inputs.analysis_request, derivatives)

    def analyze(
        self,
        request: AnalysisRequest,
        child_results: list[CellResult] | None = None,
    ) -> CellResult:
        raise InputCompositionError(
            "FundingOpenInterestCell requires a typed "
            "funding_open_interest_snapshot; execute it through analyze_inputs"
        )

    def _analyze_snapshot(
        self,
        request: AnalysisRequest,
        derivatives: FundingOpenInterestSnapshot,
    ) -> CellResult:
        if derivatives.target != request.target:
            raise InputCompositionError(
                "FundingOpenInterestCell derivatives target does not match "
                "analysis request"
            )

        bounded_points = derivatives.points[-(MAXIMUM_HISTORY_POINT_COUNT + 1) :]
        history = bounded_points[:-1]
        if len(history) < MINIMUM_HISTORY_POINT_COUNT:
            return self._insufficient_history_result(
                request,
                derivatives,
                history_count=len(history),
            )

        cadence_coverage = _cadence_coverage(
            bounded_points,
            sample_interval_ms=derivatives.sample_interval_ms,
        )
        fetch_latency_ms = (
            derivatives.provenance.fetched_at_ms
            - derivatives.provenance.event_time_ms
        )
        quality_flags = list(derivatives.provenance.quality_flags)
        active_guards = _active_guards(
            cadence_coverage=cadence_coverage,
            fetch_latency_ms=fetch_latency_ms,
            quality_flags=quality_flags,
        )
        if active_guards:
            return self._degraded_input_result(
                request,
                derivatives,
                history_count=len(history),
                cadence_coverage=cadence_coverage,
                fetch_latency_ms=fetch_latency_ms,
                quality_flags=quality_flags,
                active_guards=active_guards,
            )

        metrics = _build_metrics(
            history,
            bounded_points[-1],
            funding_interval_hours=derivatives.funding_interval_hours,
        )
        funding_crowded = (
            abs(metrics.latest_funding_8h_bps)
            >= FUNDING_CROWDING_THRESHOLD_BPS
        )
        funding_anomalous = (
            abs(
                metrics.latest_funding_8h_bps
                - metrics.historical_funding_median_8h_bps
            )
            >= MINIMUM_FUNDING_SHIFT_BPS
            and abs(metrics.funding_robust_z) >= FUNDING_ROBUST_Z_THRESHOLD
        )
        open_interest_anomalous = (
            abs(metrics.latest_open_interest_exposure_change_pct)
            >= OPEN_INTEREST_CHANGE_THRESHOLD_PCT
            and metrics.open_interest_robust_z
            >= OPEN_INTEREST_ROBUST_Z_THRESHOLD
        )
        state, direction = _classify_positioning(
            metrics,
            funding_crowded=funding_crowded,
            funding_anomalous=funding_anomalous,
            open_interest_anomalous=open_interest_anomalous,
        )
        funding_severity = _funding_severity(
            metrics,
            funding_crowded=funding_crowded,
            funding_anomalous=funding_anomalous,
        )
        open_interest_severity = _open_interest_severity(
            metrics,
            open_interest_anomalous=open_interest_anomalous,
        )
        strength = _strength(
            direction=direction,
            metrics=metrics,
            funding_severity=funding_severity,
            open_interest_severity=open_interest_severity,
        )
        volatility_risk = _volatility_risk(
            state=state,
            funding_severity=funding_severity,
            open_interest_severity=open_interest_severity,
        )
        confidence = _confidence(
            history_count=len(history),
            cadence_coverage=cadence_coverage,
            sequence=derivatives.provenance.sequence,
            funding_rate_type=derivatives.funding_rate_type,
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
            volatility_risk=volatility_risk,
            manipulation_risk=0,
            urgency=round(max(strength, volatility_risk), 4),
            score=score(direction, strength, confidence),
            explanation=_explanation(
                state=state,
                metrics=metrics,
                volatility_risk=volatility_risk,
            ),
            evidence=[
                Evidence(
                    source="derivatives.funding_rate.robust_baseline",
                    summary=(
                        f"type={derivatives.funding_rate_type}, "
                        f"latest_8h={metrics.latest_funding_8h_bps:.4f}bps, "
                        f"median_8h="
                        f"{metrics.historical_funding_median_8h_bps:.4f}bps, "
                        f"robust_z={metrics.funding_robust_z:.4f}"
                    ),
                    reliability=confidence,
                ),
                Evidence(
                    source="derivatives.open_interest.robust_change",
                    summary=(
                        f"latest_notional="
                        f"{metrics.latest_open_interest_notional:.4f} "
                        f"{derivatives.notional_currency}, "
                        f"notional_change="
                        f"{metrics.latest_open_interest_notional_change_pct:.4f}%, "
                        f"exposure_change="
                        f"{metrics.latest_open_interest_exposure_change_pct:.4f}%, "
                        f"robust_z={metrics.open_interest_robust_z:.4f}"
                    ),
                    reliability=confidence,
                ),
                Evidence(
                    source="derivatives.mark_price.alignment",
                    summary=(
                        f"latest={metrics.latest_mark_price:.4f}, "
                        f"change={metrics.latest_mark_price_change_pct:.4f}%, "
                        f"state={state}"
                    ),
                    reliability=confidence,
                ),
                Evidence(
                    source="derivatives.provenance",
                    summary=(
                        f"provider={derivatives.provenance.source_provider}, "
                        f"venue={derivatives.provenance.venue}, "
                        f"sequence={derivatives.provenance.sequence}, "
                        f"fetch_latency_ms={fetch_latency_ms}, "
                        f"cadence_coverage={cadence_coverage:.4f}"
                    ),
                    freshness=_freshness_from_latency(fetch_latency_ms),
                    reliability=90,
                ),
            ],
            metadata={
                "formula_version": self.formula_version,
                "risk_assessment_status": "available",
                "positioning_state": state,
                "history_point_count": len(history),
                "minimum_history_point_count": MINIMUM_HISTORY_POINT_COUNT,
                "maximum_history_point_count": MAXIMUM_HISTORY_POINT_COUNT,
                "funding_interval_hours": derivatives.funding_interval_hours,
                "funding_rate_type": derivatives.funding_rate_type,
                "funding_normalization_hours": FUNDING_NORMALIZATION_HOURS,
                "latest_funding_8h_bps": round(
                    metrics.latest_funding_8h_bps,
                    6,
                ),
                "historical_funding_median_8h_bps": round(
                    metrics.historical_funding_median_8h_bps,
                    6,
                ),
                "funding_mad_8h_bps": round(
                    metrics.funding_mad_8h_bps,
                    6,
                ),
                "funding_scale_8h_bps": round(
                    metrics.funding_scale_8h_bps,
                    6,
                ),
                "funding_robust_z": round(metrics.funding_robust_z, 6),
                "funding_crowded": funding_crowded,
                "funding_anomalous": funding_anomalous,
                "latest_open_interest_notional": round(
                    metrics.latest_open_interest_notional,
                    6,
                ),
                "notional_currency": derivatives.notional_currency,
                "contract_type": derivatives.contract_type,
                "latest_open_interest_notional_change_pct": round(
                    metrics.latest_open_interest_notional_change_pct,
                    6,
                ),
                "latest_open_interest_base_equivalent": round(
                    metrics.latest_open_interest_base_equivalent,
                    6,
                ),
                "latest_open_interest_exposure_change_pct": round(
                    metrics.latest_open_interest_exposure_change_pct,
                    6,
                ),
                "historical_abs_oi_change_median_pct": round(
                    metrics.historical_abs_oi_change_median_pct,
                    6,
                ),
                "open_interest_mad_pct": round(
                    metrics.open_interest_mad_pct,
                    6,
                ),
                "open_interest_scale_pct": round(
                    metrics.open_interest_scale_pct,
                    6,
                ),
                "open_interest_robust_z": round(
                    metrics.open_interest_robust_z,
                    6,
                ),
                "open_interest_anomalous": open_interest_anomalous,
                "latest_mark_price": round(metrics.latest_mark_price, 6),
                "latest_mark_price_change_pct": round(
                    metrics.latest_mark_price_change_pct,
                    6,
                ),
                "funding_severity": funding_severity,
                "open_interest_severity": open_interest_severity,
                "sample_interval_ms": derivatives.sample_interval_ms,
                "cadence_coverage": round(cadence_coverage, 6),
                "minimum_cadence_coverage": MINIMUM_CADENCE_COVERAGE,
                "source_provider": derivatives.provenance.source_provider,
                "venue": derivatives.provenance.venue,
                "market_type": derivatives.provenance.market_type,
                "provenance_sequence": derivatives.provenance.sequence,
                "source_event_id": derivatives.provenance.source_event_id,
                "event_time_ms": derivatives.provenance.event_time_ms,
                "fetched_at_ms": derivatives.provenance.fetched_at_ms,
                "fetch_latency_ms": fetch_latency_ms,
                "quality_flags": quality_flags,
                "active_guards": [],
                "funding_crowding_threshold_bps": (
                    FUNDING_CROWDING_THRESHOLD_BPS
                ),
                "minimum_funding_shift_bps": MINIMUM_FUNDING_SHIFT_BPS,
                "funding_robust_z_threshold": FUNDING_ROBUST_Z_THRESHOLD,
                "open_interest_change_threshold_pct": (
                    OPEN_INTEREST_CHANGE_THRESHOLD_PCT
                ),
                "open_interest_robust_z_threshold": (
                    OPEN_INTEREST_ROBUST_Z_THRESHOLD
                ),
                "price_direction_threshold_pct": (
                    PRICE_DIRECTION_THRESHOLD_PCT
                ),
                "single_window_confidence_cap": (
                    SINGLE_WINDOW_CONFIDENCE_CAP
                ),
                "manipulation_inference": (
                    "not_supported_by_positioning_alone"
                ),
            },
        )

    def _insufficient_history_result(
        self,
        request: AnalysisRequest,
        derivatives: FundingOpenInterestSnapshot,
        *,
        history_count: int,
    ) -> CellResult:
        confidence = round(clamp(10 + history_count * 2.5, maximum=30), 4)
        return _guarded_result(
            cell=self,
            request=request,
            derivatives=derivatives,
            state="insufficient_history",
            explanation=(
                "稳健资金费率与持仓基线至少需要 8 个历史点，"
                "当前样本不足，定位判断保持中性。"
            ),
            confidence=confidence,
            history_count=history_count,
            cadence_coverage=None,
            fetch_latency_ms=(
                derivatives.provenance.fetched_at_ms
                - derivatives.provenance.event_time_ms
            ),
            quality_flags=list(derivatives.provenance.quality_flags),
            active_guards=["insufficient_history"],
        )

    def _degraded_input_result(
        self,
        request: AnalysisRequest,
        derivatives: FundingOpenInterestSnapshot,
        *,
        history_count: int,
        cadence_coverage: float,
        fetch_latency_ms: int,
        quality_flags: list[str],
        active_guards: list[str],
    ) -> CellResult:
        return _guarded_result(
            cell=self,
            request=request,
            derivatives=derivatives,
            state="degraded_input",
            explanation=(
                "衍生品时间序列的采样连续性、抓取延迟或来源质量"
                "不满足公式边界，定位判断失败关闭。"
            ),
            confidence=20,
            history_count=history_count,
            cadence_coverage=cadence_coverage,
            fetch_latency_ms=fetch_latency_ms,
            quality_flags=quality_flags,
            active_guards=active_guards,
        )


def _guarded_result(
    *,
    cell: FundingOpenInterestCell,
    request: AnalysisRequest,
    derivatives: FundingOpenInterestSnapshot,
    state: str,
    explanation: str,
    confidence: float,
    history_count: int,
    cadence_coverage: float | None,
    fetch_latency_ms: int,
    quality_flags: list[str],
    active_guards: list[str],
) -> CellResult:
    return CellResult(
        cell_id=cell.cell_id,
        name=cell.name,
        category=cell.category,
        target=request.target,
        horizon=request.horizon,
        direction="neutral",
        strength=0,
        confidence=confidence,
        volatility_risk=0,
        manipulation_risk=0,
        urgency=0,
        score=0,
        explanation=explanation,
        evidence=[
            Evidence(
                source="derivatives.input_quality",
                summary=(
                    f"state={state}, history_count={history_count}, "
                    f"cadence_coverage={cadence_coverage}, "
                    f"fetch_latency_ms={fetch_latency_ms}, "
                    f"quality_flags={quality_flags}, guards={active_guards}"
                ),
                reliability=confidence,
            )
        ],
        metadata={
            "formula_version": cell.formula_version,
            "risk_assessment_status": "unavailable",
            "positioning_state": state,
            "history_point_count": history_count,
            "minimum_history_point_count": MINIMUM_HISTORY_POINT_COUNT,
            "maximum_history_point_count": MAXIMUM_HISTORY_POINT_COUNT,
            "sample_interval_ms": derivatives.sample_interval_ms,
            "cadence_coverage": (
                round(cadence_coverage, 6)
                if cadence_coverage is not None
                else None
            ),
            "minimum_cadence_coverage": MINIMUM_CADENCE_COVERAGE,
            "source_provider": derivatives.provenance.source_provider,
            "venue": derivatives.provenance.venue,
            "market_type": derivatives.provenance.market_type,
            "event_time_ms": derivatives.provenance.event_time_ms,
            "fetched_at_ms": derivatives.provenance.fetched_at_ms,
            "fetch_latency_ms": fetch_latency_ms,
            "quality_flags": quality_flags,
            "active_guards": active_guards,
            "single_window_confidence_cap": SINGLE_WINDOW_CONFIDENCE_CAP,
            "manipulation_inference": "not_supported_by_positioning_alone",
        },
    )


def _build_metrics(
    history: list[FundingOpenInterestPoint],
    latest: FundingOpenInterestPoint,
    *,
    funding_interval_hours: float,
) -> _PositioningMetrics:
    funding_multiplier = FUNDING_NORMALIZATION_HOURS / funding_interval_hours
    historical_funding_bps = [
        point.funding_rate * funding_multiplier * 10_000
        for point in history
    ]
    latest_funding_bps = latest.funding_rate * funding_multiplier * 10_000
    funding_median = median(historical_funding_bps)
    funding_mad = median(
        abs(value - funding_median) for value in historical_funding_bps
    )
    funding_scale = 1.4826 * max(funding_mad, FUNDING_MAD_FLOOR_BPS)
    funding_robust_z = (latest_funding_bps - funding_median) / funding_scale

    historical_oi_exposures = [
        point.open_interest_notional / point.mark_price
        for point in history
    ]
    historical_oi_changes = [
        _percentage_change(
            historical_oi_exposures[index - 1],
            historical_oi_exposures[index],
        )
        for index in range(1, len(history))
    ]
    historical_abs_oi_changes = [abs(value) for value in historical_oi_changes]
    historical_abs_oi_median = median(historical_abs_oi_changes)
    open_interest_mad = median(
        abs(value - historical_abs_oi_median)
        for value in historical_abs_oi_changes
    )
    open_interest_scale = 1.4826 * max(
        open_interest_mad,
        OPEN_INTEREST_MAD_FLOOR_PCT,
    )
    previous = history[-1]
    latest_open_interest_base_equivalent = (
        latest.open_interest_notional / latest.mark_price
    )
    latest_oi_exposure_change = _percentage_change(
        historical_oi_exposures[-1],
        latest_open_interest_base_equivalent,
    )
    latest_oi_notional_change = _percentage_change(
        previous.open_interest_notional,
        latest.open_interest_notional,
    )
    open_interest_robust_z = max(
        0.0,
        (abs(latest_oi_exposure_change) - historical_abs_oi_median)
        / open_interest_scale,
    )

    return _PositioningMetrics(
        latest_funding_8h_bps=latest_funding_bps,
        historical_funding_median_8h_bps=funding_median,
        funding_mad_8h_bps=funding_mad,
        funding_scale_8h_bps=funding_scale,
        funding_robust_z=funding_robust_z,
        latest_open_interest_notional=latest.open_interest_notional,
        latest_open_interest_notional_change_pct=latest_oi_notional_change,
        latest_open_interest_base_equivalent=(
            latest_open_interest_base_equivalent
        ),
        latest_open_interest_exposure_change_pct=latest_oi_exposure_change,
        historical_abs_oi_change_median_pct=historical_abs_oi_median,
        open_interest_mad_pct=open_interest_mad,
        open_interest_scale_pct=open_interest_scale,
        open_interest_robust_z=open_interest_robust_z,
        latest_mark_price=latest.mark_price,
        latest_mark_price_change_pct=_percentage_change(
            previous.mark_price,
            latest.mark_price,
        ),
    )


def _percentage_change(previous: float, latest: float) -> float:
    return (latest / previous - 1.0) * 100


def _cadence_coverage(
    points: list[FundingOpenInterestPoint],
    *,
    sample_interval_ms: int,
) -> float:
    gaps = [
        points[index].timestamp_ms - points[index - 1].timestamp_ms
        for index in range(1, len(points))
    ]
    if not gaps:
        return 0.0
    tolerance_ms = sample_interval_ms * CADENCE_TOLERANCE_RATIO
    accepted = sum(
        1
        for gap in gaps
        if abs(gap - sample_interval_ms) <= tolerance_ms
    )
    return accepted / len(gaps)


def _active_guards(
    *,
    cadence_coverage: float,
    fetch_latency_ms: int,
    quality_flags: list[str],
) -> list[str]:
    guards: list[str] = []
    if cadence_coverage < MINIMUM_CADENCE_COVERAGE:
        guards.append("irregular_cadence")
    if quality_flags:
        guards.append("quality_flags")
    if fetch_latency_ms < 0:
        guards.append("invalid_fetch_latency")
    elif fetch_latency_ms > MAX_ACCEPTABLE_FETCH_LATENCY_MS:
        guards.append("delayed_fetch")
    return guards


def _classify_positioning(
    metrics: _PositioningMetrics,
    *,
    funding_crowded: bool,
    funding_anomalous: bool,
    open_interest_anomalous: bool,
) -> tuple[str, str]:
    oi_change = metrics.latest_open_interest_exposure_change_pct
    price_change = metrics.latest_mark_price_change_pct
    if open_interest_anomalous:
        if price_change >= PRICE_DIRECTION_THRESHOLD_PCT:
            if oi_change > 0:
                if (
                    funding_crowded
                    and metrics.latest_funding_8h_bps > 0
                ):
                    return "crowded_long_buildup", "conflict"
                return "leveraged_long_buildup", "bullish"
            return "short_covering", "bullish"
        if price_change <= -PRICE_DIRECTION_THRESHOLD_PCT:
            if oi_change > 0:
                if (
                    funding_crowded
                    and metrics.latest_funding_8h_bps < 0
                ):
                    return "crowded_short_buildup", "conflict"
                return "leveraged_short_buildup", "bearish"
            return "long_liquidation", "bearish"
        if oi_change > 0:
            return "open_interest_surge_without_price_confirmation", "conflict"
        return "deleveraging_without_price_confirmation", "conflict"

    if funding_crowded:
        if metrics.latest_funding_8h_bps > 0:
            return "positive_funding_crowding", "conflict"
        return "negative_funding_crowding", "conflict"
    if funding_anomalous:
        if metrics.funding_robust_z > 0:
            return "funding_shift_up", "conflict"
        return "funding_shift_down", "conflict"
    return "normal", "neutral"


def _funding_severity(
    metrics: _PositioningMetrics,
    *,
    funding_crowded: bool,
    funding_anomalous: bool,
) -> float:
    if not funding_crowded and not funding_anomalous:
        return 0.0
    level_component = clamp(
        abs(metrics.latest_funding_8h_bps)
        / FUNDING_CROWDING_THRESHOLD_BPS
        * 60,
        maximum=95,
    )
    deviation_component = clamp(
        abs(metrics.funding_robust_z) / FUNDING_ROBUST_Z_THRESHOLD * 55,
        maximum=90,
    )
    return round(max(level_component, deviation_component), 4)


def _open_interest_severity(
    metrics: _PositioningMetrics,
    *,
    open_interest_anomalous: bool,
) -> float:
    if not open_interest_anomalous:
        return 0.0
    change_component = clamp(
        abs(metrics.latest_open_interest_exposure_change_pct)
        / OPEN_INTEREST_CHANGE_THRESHOLD_PCT
        * 55,
        maximum=95,
    )
    deviation_component = clamp(
        metrics.open_interest_robust_z
        / OPEN_INTEREST_ROBUST_Z_THRESHOLD
        * 55,
        maximum=90,
    )
    return round(max(change_component, deviation_component), 4)


def _strength(
    *,
    direction: str,
    metrics: _PositioningMetrics,
    funding_severity: float,
    open_interest_severity: float,
) -> float:
    if direction == "neutral":
        return 0.0
    if direction == "conflict":
        return round(max(funding_severity, open_interest_severity), 4)
    price_component = clamp(
        abs(metrics.latest_mark_price_change_pct)
        / PRICE_DIRECTION_THRESHOLD_PCT
        * 10,
        maximum=20,
    )
    return round(
        clamp(open_interest_severity * 0.82 + price_component, maximum=92),
        4,
    )


def _volatility_risk(
    *,
    state: str,
    funding_severity: float,
    open_interest_severity: float,
) -> float:
    value = max(
        funding_severity * 0.75,
        open_interest_severity * 0.85,
    )
    if state in {
        "crowded_long_buildup",
        "crowded_short_buildup",
        "long_liquidation",
        "short_covering",
    }:
        value += 10
    return round(clamp(value), 4)


def _confidence(
    *,
    history_count: int,
    cadence_coverage: float,
    sequence: int | None,
    funding_rate_type: str,
) -> float:
    value = (
        42
        + min(history_count, MAXIMUM_HISTORY_POINT_COUNT) * 0.75
        + cadence_coverage * 8
        + (2 if sequence is not None else 0)
        - (5 if funding_rate_type == "predicted" else 0)
    )
    return round(clamp(value, maximum=SINGLE_WINDOW_CONFIDENCE_CAP), 4)


def _freshness_from_latency(fetch_latency_ms: int) -> float:
    if fetch_latency_ms < 0:
        return 0.0
    return round(
        clamp(
            100 - fetch_latency_ms / MAX_ACCEPTABLE_FETCH_LATENCY_MS * 40
        ),
        4,
    )


def _explanation(
    *,
    state: str,
    metrics: _PositioningMetrics,
    volatility_risk: float,
) -> str:
    state_text = {
        "normal": "资金费率与持仓变化均未脱离稳健基线",
        "positive_funding_crowding": "正资金费率处于拥挤区间",
        "negative_funding_crowding": "负资金费率处于拥挤区间",
        "funding_shift_up": "资金费率相对历史基线显著抬升",
        "funding_shift_down": "资金费率相对历史基线显著下移",
        "leveraged_long_buildup": "价格上涨并伴随异常增仓",
        "leveraged_short_buildup": "价格下跌并伴随异常增仓",
        "crowded_long_buildup": "价格上涨、异常增仓且多头资金费率拥挤",
        "crowded_short_buildup": "价格下跌、异常增仓且空头资金费率拥挤",
        "long_liquidation": "价格下跌并伴随异常减仓，符合多头去杠杆形态",
        "short_covering": "价格上涨并伴随异常减仓，符合空头回补形态",
        "open_interest_surge_without_price_confirmation": (
            "持仓异常增加但价格没有同步确认"
        ),
        "deleveraging_without_price_confirmation": (
            "持仓异常下降但价格没有同步确认"
        ),
    }[state]
    return (
        f"{state_text}；8 小时标准化资金费率为 "
        f"{metrics.latest_funding_8h_bps:.2f}bps，持仓变化 "
        f"{metrics.latest_open_interest_exposure_change_pct:.2f}%，"
        "标记价格变化 "
        f"{metrics.latest_mark_price_change_pct:.2f}%，杠杆波动风险估计为 "
        f"{volatility_risk:.1f}/100。该结果描述仓位结构，不单独证明操纵。"
    )
