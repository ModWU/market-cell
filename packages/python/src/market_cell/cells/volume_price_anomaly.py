from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from market_cell.cells.base import MarketCell
from market_cell.models import AnalysisRequest, Candle, CellResult, Evidence
from market_cell.scoring import clamp, score


MINIMUM_HISTORY_CANDLE_COUNT = 8
MAXIMUM_HISTORY_CANDLE_COUNT = 48
VOLUME_RATIO_THRESHOLD = 2.0
ROBUST_Z_THRESHOLD = 3.5
MINIMUM_PRICE_MOVE_PCT = 1.5
MUTED_PRICE_MOVE_PCT = 0.5
MINIMUM_POSITIVE_VOLUME_COVERAGE = 0.80
VOLUME_RELATIVE_MAD_FLOOR = 0.10
RETURN_MAD_FLOOR_PCT = 0.15
SINGLE_WINDOW_CONFIDENCE_CAP = 88.0

KNOWN_ANOMALY_STATES = {
    "insufficient_history",
    "invalid_volume_baseline",
    "degraded_volume_baseline",
    "normal",
    "volume_absorption",
    "volume_price_divergence",
    "price_dislocation_up",
    "price_dislocation_down",
    "synchronized_expansion_up",
    "synchronized_expansion_down",
}


@dataclass(frozen=True)
class _VolumePriceMetrics:
    latest_volume: float
    historical_volume_median: float
    volume_ratio: float
    volume_relative_mad: float
    volume_scale: float
    volume_robust_z: float
    latest_return_pct: float
    historical_abs_return_median_pct: float
    return_mad_pct: float
    return_scale_pct: float
    price_robust_z: float
    muted_price_threshold_pct: float


class VolumePriceAnomalyCell(MarketCell):
    cell_id = "risk.volume_price_anomaly"
    name = "VolumePriceAnomalyCell"
    category = "risk"
    description = (
        "使用有界历史窗口和稳健统计识别最新 K 线的异常放量、"
        "价格脱离和量价背离，不把异常模式直接解释为操纵。"
    )
    formula_version = "robust_volume_price_anomaly_v0.2"
    inputs = ["candles.close", "candles.volume"]
    outputs = [
        "direction",
        "strength",
        "confidence",
        "volatility_risk",
        "manipulation_risk",
        "anomaly_state",
        "volume_ratio",
        "volume_robust_z",
        "latest_return_pct",
        "price_robust_z",
    ]
    risk_dimensions = ["volatility_risk", "manipulation_risk"]
    status = "experimental"

    def analyze(
        self,
        request: AnalysisRequest,
        child_results: list[CellResult] | None = None,
    ) -> CellResult:
        history = request.candles[-(MAXIMUM_HISTORY_CANDLE_COUNT + 1) : -1]
        if len(history) < MINIMUM_HISTORY_CANDLE_COUNT:
            return self._insufficient_history_result(request, len(history))

        positive_volume_count = sum(
            1 for candle in history if candle.volume > 0
        )
        positive_volume_coverage = positive_volume_count / len(history)
        historical_volume_median = median(candle.volume for candle in history)
        if historical_volume_median <= 0:
            return self._invalid_volume_baseline_result(
                request,
                history_count=len(history),
                historical_volume_median=historical_volume_median,
                positive_volume_count=positive_volume_count,
                positive_volume_coverage=positive_volume_coverage,
            )
        if positive_volume_coverage < MINIMUM_POSITIVE_VOLUME_COVERAGE:
            return self._degraded_volume_baseline_result(
                request,
                history_count=len(history),
                historical_volume_median=historical_volume_median,
                positive_volume_count=positive_volume_count,
                positive_volume_coverage=positive_volume_coverage,
            )

        metrics = _build_metrics(
            history,
            request.candles[-1],
            historical_volume_median=historical_volume_median,
        )
        volume_anomalous = (
            metrics.volume_ratio >= VOLUME_RATIO_THRESHOLD
            and metrics.volume_robust_z >= ROBUST_Z_THRESHOLD
        )
        latest_abs_return_pct = abs(metrics.latest_return_pct)
        price_anomalous = (
            latest_abs_return_pct >= MINIMUM_PRICE_MOVE_PCT
            and metrics.price_robust_z >= ROBUST_Z_THRESHOLD
        )
        state = _anomaly_state(
            volume_anomalous=volume_anomalous,
            price_anomalous=price_anomalous,
            latest_return_pct=metrics.latest_return_pct,
            muted_price_threshold_pct=metrics.muted_price_threshold_pct,
        )
        direction = "neutral" if state == "normal" else "conflict"
        volume_severity = _volume_severity(metrics, volume_anomalous)
        price_severity = _price_severity(metrics, price_anomalous)
        anomaly_score = _anomaly_score(
            state,
            volume_severity=volume_severity,
            price_severity=price_severity,
        )
        manipulation_risk, volatility_risk = _risk_dimensions(
            state,
            anomaly_score=anomaly_score,
            price_severity=price_severity,
        )
        confidence = _confidence(len(history))

        return CellResult(
            cell_id=self.cell_id,
            name=self.name,
            category=self.category,
            target=request.target,
            horizon=request.horizon,
            direction=direction,
            strength=anomaly_score,
            confidence=confidence,
            volatility_risk=volatility_risk,
            manipulation_risk=manipulation_risk,
            urgency=round(max(volatility_risk, manipulation_risk), 4),
            score=score(direction, anomaly_score, confidence),
            explanation=_explanation(
                state=state,
                metrics=metrics,
                anomaly_score=anomaly_score,
            ),
            evidence=[
                Evidence(
                    source="candles.volume.robust_baseline",
                    summary=(
                        f"latest={metrics.latest_volume:.4f}, "
                        f"median={metrics.historical_volume_median:.4f}, "
                        f"ratio={metrics.volume_ratio:.4f}, "
                        f"robust_z={metrics.volume_robust_z:.4f}"
                    ),
                    reliability=confidence,
                ),
                Evidence(
                    source="candles.close.robust_return",
                    summary=(
                        f"latest_return={metrics.latest_return_pct:.4f}%, "
                        f"historical_abs_median="
                        f"{metrics.historical_abs_return_median_pct:.4f}%, "
                        f"robust_z={metrics.price_robust_z:.4f}"
                    ),
                    reliability=confidence,
                ),
                Evidence(
                    source="volume_price.anomaly_classification",
                    summary=(
                        f"state={state}, anomaly_score={anomaly_score:.4f}; "
                        "abnormal co-movement is risk evidence, not proof of "
                        "manipulation"
                    ),
                    reliability=confidence,
                ),
            ],
            metadata={
                "formula_version": self.formula_version,
                "anomaly_state": state,
                "history_candle_count": len(history),
                "minimum_history_candle_count": MINIMUM_HISTORY_CANDLE_COUNT,
                "maximum_history_candle_count": MAXIMUM_HISTORY_CANDLE_COUNT,
                "positive_volume_count": positive_volume_count,
                "positive_volume_coverage": round(
                    positive_volume_coverage,
                    6,
                ),
                "minimum_positive_volume_coverage": (
                    MINIMUM_POSITIVE_VOLUME_COVERAGE
                ),
                "latest_volume": round(metrics.latest_volume, 6),
                "historical_volume_median": round(
                    metrics.historical_volume_median,
                    6,
                ),
                "volume_ratio": round(metrics.volume_ratio, 6),
                "volume_relative_mad": round(
                    metrics.volume_relative_mad,
                    6,
                ),
                "volume_scale": round(metrics.volume_scale, 6),
                "volume_robust_z": round(metrics.volume_robust_z, 6),
                "latest_return_pct": round(metrics.latest_return_pct, 6),
                "price_direction": _price_direction(metrics.latest_return_pct),
                "historical_abs_return_median_pct": round(
                    metrics.historical_abs_return_median_pct,
                    6,
                ),
                "return_mad_pct": round(metrics.return_mad_pct, 6),
                "return_scale_pct": round(metrics.return_scale_pct, 6),
                "price_robust_z": round(metrics.price_robust_z, 6),
                "muted_price_threshold_pct": round(
                    metrics.muted_price_threshold_pct,
                    6,
                ),
                "volume_anomalous": volume_anomalous,
                "price_anomalous": price_anomalous,
                "volume_severity": volume_severity,
                "price_severity": price_severity,
                "anomaly_score": anomaly_score,
                "volume_ratio_threshold": VOLUME_RATIO_THRESHOLD,
                "robust_z_threshold": ROBUST_Z_THRESHOLD,
                "minimum_price_move_pct": MINIMUM_PRICE_MOVE_PCT,
                "single_window_confidence_cap": SINGLE_WINDOW_CONFIDENCE_CAP,
                "manipulation_inference": "risk_pattern_not_proof",
            },
        )

    def _insufficient_history_result(
        self,
        request: AnalysisRequest,
        history_count: int,
    ) -> CellResult:
        confidence = round(clamp(10 + history_count * 3, maximum=30), 4)
        return CellResult(
            cell_id=self.cell_id,
            name=self.name,
            category=self.category,
            target=request.target,
            horizon=request.horizon,
            direction="neutral",
            strength=0,
            confidence=confidence,
            volatility_risk=0,
            manipulation_risk=0,
            urgency=0,
            score=0,
            explanation=(
                "稳健量价基线至少需要 8 根历史 K 线，当前样本不足，"
                "异常判断保持中性。"
            ),
            evidence=[
                Evidence(
                    source="candles.history",
                    summary=(
                        f"history_count={history_count}, "
                        f"minimum={MINIMUM_HISTORY_CANDLE_COUNT}"
                    ),
                    reliability=confidence,
                )
            ],
            metadata={
                "formula_version": self.formula_version,
                "anomaly_state": "insufficient_history",
                "history_candle_count": history_count,
                "minimum_history_candle_count": MINIMUM_HISTORY_CANDLE_COUNT,
                "maximum_history_candle_count": MAXIMUM_HISTORY_CANDLE_COUNT,
                "manipulation_inference": "risk_pattern_not_proof",
            },
        )

    def _invalid_volume_baseline_result(
        self,
        request: AnalysisRequest,
        *,
        history_count: int,
        historical_volume_median: float,
        positive_volume_count: int,
        positive_volume_coverage: float,
    ) -> CellResult:
        return CellResult(
            cell_id=self.cell_id,
            name=self.name,
            category=self.category,
            target=request.target,
            horizon=request.horizon,
            direction="neutral",
            strength=0,
            confidence=20,
            volatility_risk=0,
            manipulation_risk=0,
            urgency=0,
            score=0,
            explanation=(
                "历史成交量中位数不为正，无法建立可靠量价基线，"
                "异常判断保持中性。"
            ),
            evidence=[
                Evidence(
                    source="candles.volume.robust_baseline",
                    summary=(
                        f"historical_volume_median="
                        f"{historical_volume_median:.4f}"
                    ),
                    reliability=20,
                )
            ],
            metadata={
                "formula_version": self.formula_version,
                "anomaly_state": "invalid_volume_baseline",
                "history_candle_count": history_count,
                "minimum_history_candle_count": MINIMUM_HISTORY_CANDLE_COUNT,
                "maximum_history_candle_count": MAXIMUM_HISTORY_CANDLE_COUNT,
                "historical_volume_median": historical_volume_median,
                "positive_volume_count": positive_volume_count,
                "positive_volume_coverage": round(
                    positive_volume_coverage,
                    6,
                ),
                "minimum_positive_volume_coverage": (
                    MINIMUM_POSITIVE_VOLUME_COVERAGE
                ),
                "manipulation_inference": "risk_pattern_not_proof",
            },
        )

    def _degraded_volume_baseline_result(
        self,
        request: AnalysisRequest,
        *,
        history_count: int,
        historical_volume_median: float,
        positive_volume_count: int,
        positive_volume_coverage: float,
    ) -> CellResult:
        return CellResult(
            cell_id=self.cell_id,
            name=self.name,
            category=self.category,
            target=request.target,
            horizon=request.horizon,
            direction="neutral",
            strength=0,
            confidence=25,
            volatility_risk=0,
            manipulation_risk=0,
            urgency=0,
            score=0,
            explanation=(
                "历史窗口的正成交量覆盖率不足，稳健基线可能被缺失或"
                "停滞数据扭曲，异常判断失败关闭。"
            ),
            evidence=[
                Evidence(
                    source="candles.volume.baseline_coverage",
                    summary=(
                        f"positive_volume_count={positive_volume_count}, "
                        f"history_count={history_count}, "
                        f"coverage={positive_volume_coverage:.4f}, "
                        f"minimum={MINIMUM_POSITIVE_VOLUME_COVERAGE:.4f}"
                    ),
                    reliability=25,
                )
            ],
            metadata={
                "formula_version": self.formula_version,
                "anomaly_state": "degraded_volume_baseline",
                "history_candle_count": history_count,
                "minimum_history_candle_count": MINIMUM_HISTORY_CANDLE_COUNT,
                "maximum_history_candle_count": MAXIMUM_HISTORY_CANDLE_COUNT,
                "historical_volume_median": historical_volume_median,
                "positive_volume_count": positive_volume_count,
                "positive_volume_coverage": round(
                    positive_volume_coverage,
                    6,
                ),
                "minimum_positive_volume_coverage": (
                    MINIMUM_POSITIVE_VOLUME_COVERAGE
                ),
                "manipulation_inference": "risk_pattern_not_proof",
            },
        )


def _build_metrics(
    history: list[Candle],
    latest: Candle,
    *,
    historical_volume_median: float,
) -> _VolumePriceMetrics:
    volume_ratio = latest.volume / historical_volume_median
    relative_volume_deviations = [
        abs(candle.volume / historical_volume_median - 1) for candle in history
    ]
    volume_relative_mad = median(relative_volume_deviations)
    volume_scale = 1.4826 * max(
        volume_relative_mad,
        VOLUME_RELATIVE_MAD_FLOOR,
    )
    volume_robust_z = (volume_ratio - 1) / volume_scale

    historical_abs_returns = [
        abs((current.close - previous.close) / previous.close * 100)
        for previous, current in zip(history, history[1:])
        if previous.close
    ]
    historical_abs_return_median_pct = median(historical_abs_returns)
    return_deviations = [
        abs(value - historical_abs_return_median_pct)
        for value in historical_abs_returns
    ]
    return_mad_pct = median(return_deviations)
    return_scale_pct = 1.4826 * max(
        return_mad_pct,
        RETURN_MAD_FLOOR_PCT,
    )
    latest_return_pct = (
        (latest.close - history[-1].close) / history[-1].close * 100
    )
    price_robust_z = (
        abs(latest_return_pct) - historical_abs_return_median_pct
    ) / return_scale_pct
    muted_price_threshold_pct = max(
        MUTED_PRICE_MOVE_PCT,
        historical_abs_return_median_pct + 1.5 * return_scale_pct,
    )
    return _VolumePriceMetrics(
        latest_volume=latest.volume,
        historical_volume_median=historical_volume_median,
        volume_ratio=volume_ratio,
        volume_relative_mad=volume_relative_mad,
        volume_scale=volume_scale,
        volume_robust_z=volume_robust_z,
        latest_return_pct=latest_return_pct,
        historical_abs_return_median_pct=(
            historical_abs_return_median_pct
        ),
        return_mad_pct=return_mad_pct,
        return_scale_pct=return_scale_pct,
        price_robust_z=price_robust_z,
        muted_price_threshold_pct=muted_price_threshold_pct,
    )


def _anomaly_state(
    *,
    volume_anomalous: bool,
    price_anomalous: bool,
    latest_return_pct: float,
    muted_price_threshold_pct: float,
) -> str:
    if volume_anomalous and price_anomalous:
        return (
            "synchronized_expansion_up"
            if latest_return_pct > 0
            else "synchronized_expansion_down"
        )
    if volume_anomalous:
        if abs(latest_return_pct) <= muted_price_threshold_pct:
            return "volume_absorption"
        return "volume_price_divergence"
    if price_anomalous:
        return (
            "price_dislocation_up"
            if latest_return_pct > 0
            else "price_dislocation_down"
        )
    return "normal"


def _volume_severity(
    metrics: _VolumePriceMetrics,
    volume_anomalous: bool,
) -> float:
    if not volume_anomalous:
        return 0.0
    value = (
        35
        + (metrics.volume_ratio - VOLUME_RATIO_THRESHOLD) * 20
        + (min(metrics.volume_robust_z, 10) - ROBUST_Z_THRESHOLD) * 4
    )
    return round(clamp(value), 4)


def _price_severity(
    metrics: _VolumePriceMetrics,
    price_anomalous: bool,
) -> float:
    if not price_anomalous:
        return 0.0
    value = (
        35
        + (abs(metrics.latest_return_pct) - MINIMUM_PRICE_MOVE_PCT) * 8
        + (min(metrics.price_robust_z, 10) - ROBUST_Z_THRESHOLD) * 4
    )
    return round(clamp(value), 4)


def _anomaly_score(
    state: str,
    *,
    volume_severity: float,
    price_severity: float,
) -> float:
    if state in {
        "normal",
        "insufficient_history",
        "invalid_volume_baseline",
        "degraded_volume_baseline",
    }:
        return 0.0
    if state.startswith("synchronized_expansion"):
        return round(clamp((volume_severity + price_severity) / 2), 4)
    return round(max(volume_severity, price_severity), 4)


def _risk_dimensions(
    state: str,
    *,
    anomaly_score: float,
    price_severity: float,
) -> tuple[float, float]:
    if state.startswith("synchronized_expansion"):
        return (
            round(clamp(anomaly_score * 0.35), 4),
            round(clamp(max(45, price_severity)), 4),
        )
    if state == "volume_absorption":
        return (
            round(clamp(anomaly_score * 0.65), 4),
            round(clamp(anomaly_score * 0.25), 4),
        )
    if state == "volume_price_divergence":
        return (
            round(clamp(anomaly_score * 0.55), 4),
            round(clamp(anomaly_score * 0.40), 4),
        )
    if state.startswith("price_dislocation"):
        return (
            round(clamp(anomaly_score * 0.45), 4),
            round(clamp(max(45, price_severity)), 4),
        )
    return 0.0, 0.0


def _confidence(history_count: int) -> float:
    return round(
        clamp(
            40 + min(history_count, 32) * 1.5,
            maximum=SINGLE_WINDOW_CONFIDENCE_CAP,
        ),
        4,
    )


def _price_direction(latest_return_pct: float) -> str:
    if latest_return_pct > 0:
        return "up"
    if latest_return_pct < 0:
        return "down"
    return "flat"


def _explanation(
    *,
    state: str,
    metrics: _VolumePriceMetrics,
    anomaly_score: float,
) -> str:
    state_text = {
        "normal": "最新量价关系仍在稳健历史基线内",
        "volume_absorption": "成交量异常放大但收盘价格几乎未位移，呈现吸收或换手特征",
        "volume_price_divergence": "成交量异常放大，但价格位移没有达到同步异常标准",
        "price_dislocation_up": "价格向上异常位移，但成交量没有同步异常放大",
        "price_dislocation_down": "价格向下异常位移，但成交量没有同步异常放大",
        "synchronized_expansion_up": "成交量与价格向上位移同时显著偏离历史基线",
        "synchronized_expansion_down": "成交量与价格向下位移同时显著偏离历史基线",
    }[state]
    return (
        f"{state_text}。成交量为历史中位数的 {metrics.volume_ratio:.2f} 倍，"
        f"最新收盘变化 {metrics.latest_return_pct:.2f}%，"
        f"异常强度 {anomaly_score:.1f}/100。该结果只标记异常风险模式，"
        "不能证明市场操纵或交易者意图。"
    )
