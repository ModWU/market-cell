from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from market_cell.data.quality import inspect_candles
from market_cell.data.sources import CandleBatch
from market_cell.data.timeframes import interval_to_millis, timestamp_to_ms
from market_cell.models import Candle


Severity = Literal["info", "warning", "critical"]


@dataclass(frozen=True)
class DataQualityIssue:
    code: str
    severity: Severity
    message: str
    source_provider: str
    symbol: str
    horizon: str
    timestamp: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceQualityReport:
    source_provider: str
    symbol: str
    horizon: str
    is_usable: bool
    quality_score: float
    issues: list[DataQualityIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceComparisonReport:
    primary_provider: str
    reference_provider: str
    symbol: str
    horizon: str
    is_usable: bool
    max_close_deviation_pct: float
    issues: list[DataQualityIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SourceQualityMonitor:
    def __init__(
        self,
        gap_multiplier: float = 1.5,
        volume_spike_threshold: float = 8.0,
        range_spike_threshold: float = 5.0,
        stale_after_ms: int | None = None,
        cross_source_deviation_pct: float = 1.0,
    ) -> None:
        self.gap_multiplier = gap_multiplier
        self.volume_spike_threshold = volume_spike_threshold
        self.range_spike_threshold = range_spike_threshold
        self.stale_after_ms = stale_after_ms
        self.cross_source_deviation_pct = cross_source_deviation_pct

    def inspect_batch(self, batch: CandleBatch, now: str | None = None) -> SourceQualityReport:
        issues: list[DataQualityIssue] = []
        base_report = inspect_candles(batch.candles)
        for issue in base_report.issues:
            issues.append(
                self._issue(
                    batch=batch,
                    code="invalid_ohlcv",
                    severity="critical",
                    message=issue,
                )
            )

        if batch.candles:
            issues.extend(self._detect_gaps(batch))
            issues.extend(self._detect_staleness(batch, now))
            issues.extend(self._detect_volume_spike(batch))
            issues.extend(self._detect_range_spike(batch))

        return SourceQualityReport(
            source_provider=batch.source.provider,
            symbol=batch.query.symbol,
            horizon=batch.query.horizon,
            is_usable=not any(issue.severity == "critical" for issue in issues),
            quality_score=_quality_score(issues),
            issues=issues,
        )

    def compare_sources(self, primary: CandleBatch, reference: CandleBatch) -> SourceComparisonReport:
        primary_by_time = {candle.timestamp: candle for candle in primary.candles}
        reference_by_time = {candle.timestamp: candle for candle in reference.candles}
        common_timestamps = sorted(set(primary_by_time) & set(reference_by_time))
        issues: list[DataQualityIssue] = []

        if not common_timestamps:
            issues.append(
                self._issue(
                    batch=primary,
                    code="cross_source_no_overlap",
                    severity="warning",
                    message="两个数据源没有可比较的重叠 K 线",
                    metadata={"reference_provider": reference.source.provider},
                )
            )
            return SourceComparisonReport(
                primary_provider=primary.source.provider,
                reference_provider=reference.source.provider,
                symbol=primary.query.symbol,
                horizon=primary.query.horizon,
                is_usable=True,
                max_close_deviation_pct=0,
                issues=issues,
            )

        max_deviation = 0.0
        max_timestamp: str | None = None
        for timestamp in common_timestamps:
            primary_close = primary_by_time[timestamp].close
            reference_close = reference_by_time[timestamp].close
            deviation = _pct_deviation(primary_close, reference_close)
            if deviation > max_deviation:
                max_deviation = deviation
                max_timestamp = timestamp

        if max_deviation > self.cross_source_deviation_pct:
            issues.append(
                self._issue(
                    batch=primary,
                    code="cross_source_close_deviation",
                    severity="warning",
                    message="主数据源和参考数据源的收盘价偏差超过阈值",
                    timestamp=max_timestamp,
                    metadata={
                        "reference_provider": reference.source.provider,
                        "max_close_deviation_pct": round(max_deviation, 6),
                        "threshold_pct": self.cross_source_deviation_pct,
                    },
                )
            )

        return SourceComparisonReport(
            primary_provider=primary.source.provider,
            reference_provider=reference.source.provider,
            symbol=primary.query.symbol,
            horizon=primary.query.horizon,
            is_usable=not any(issue.severity == "critical" for issue in issues),
            max_close_deviation_pct=max_deviation,
            issues=issues,
        )

    def _detect_gaps(self, batch: CandleBatch) -> list[DataQualityIssue]:
        interval_ms = interval_to_millis(batch.query.horizon)
        if interval_ms <= 0 or len(batch.candles) < 2:
            return []

        issues: list[DataQualityIssue] = []
        try:
            previous_ms = timestamp_to_ms(batch.candles[0].timestamp)
        except ValueError as exc:
            return [
                self._issue(
                    batch=batch,
                    code="invalid_timestamp",
                    severity="critical",
                    message=str(exc),
                    timestamp=batch.candles[0].timestamp,
                )
            ]
        for candle in batch.candles[1:]:
            try:
                current_ms = timestamp_to_ms(candle.timestamp)
            except ValueError as exc:
                issues.append(
                    self._issue(
                        batch=batch,
                        code="invalid_timestamp",
                        severity="critical",
                        message=str(exc),
                        timestamp=candle.timestamp,
                    )
                )
                continue
            gap_ms = current_ms - previous_ms
            if gap_ms > interval_ms * self.gap_multiplier:
                issues.append(
                    self._issue(
                        batch=batch,
                        code="time_gap",
                        severity="warning",
                        message="K 线时间序列存在缺口",
                        timestamp=candle.timestamp,
                        metadata={"gap_ms": gap_ms, "expected_interval_ms": interval_ms},
                    )
                )
            previous_ms = current_ms
        return issues

    def _detect_staleness(self, batch: CandleBatch, now: str | None) -> list[DataQualityIssue]:
        if self.stale_after_ms is None or now is None or not batch.candles:
            return []

        interval_ms = interval_to_millis(batch.query.horizon)
        latest = batch.candles[-1]
        try:
            latest_close_ms = timestamp_to_ms(latest.timestamp) + max(interval_ms - 1, 0)
            lag_ms = timestamp_to_ms(now) - latest_close_ms
        except ValueError as exc:
            return [
                self._issue(
                    batch=batch,
                    code="invalid_timestamp",
                    severity="critical",
                    message=str(exc),
                    timestamp=latest.timestamp,
                )
            ]
        if lag_ms <= self.stale_after_ms:
            return []

        return [
            self._issue(
                batch=batch,
                code="stale_data",
                severity="warning",
                message="最新 K 线距离当前时间过久",
                timestamp=latest.timestamp,
                metadata={"lag_ms": lag_ms, "stale_after_ms": self.stale_after_ms},
            )
        ]

    def _detect_volume_spike(self, batch: CandleBatch) -> list[DataQualityIssue]:
        if len(batch.candles) < 3:
            return []

        latest = batch.candles[-1]
        baseline = sum(candle.volume for candle in batch.candles[:-1]) / (len(batch.candles) - 1)
        if baseline <= 0:
            return []
        ratio = latest.volume / baseline
        if ratio < self.volume_spike_threshold:
            return []

        return [
            self._issue(
                batch=batch,
                code="volume_spike",
                severity="warning",
                message="最新 K 线成交量显著高于历史均值",
                timestamp=latest.timestamp,
                metadata={"volume_ratio": round(ratio, 6), "threshold": self.volume_spike_threshold},
            )
        ]

    def _detect_range_spike(self, batch: CandleBatch) -> list[DataQualityIssue]:
        if len(batch.candles) < 3:
            return []

        latest = batch.candles[-1]
        baseline_ranges = [_range_pct(candle) for candle in batch.candles[:-1] if _range_pct(candle) > 0]
        if not baseline_ranges:
            return []
        baseline = sum(baseline_ranges) / len(baseline_ranges)
        latest_range = _range_pct(latest)
        if baseline <= 0 or latest_range / baseline < self.range_spike_threshold:
            return []

        return [
            self._issue(
                batch=batch,
                code="range_spike",
                severity="warning",
                message="最新 K 线振幅显著高于历史均值",
                timestamp=latest.timestamp,
                metadata={
                    "range_ratio": round(latest_range / baseline, 6),
                    "latest_range_pct": round(latest_range, 6),
                    "threshold": self.range_spike_threshold,
                },
            )
        ]

    def _issue(
        self,
        batch: CandleBatch,
        code: str,
        severity: Severity,
        message: str,
        timestamp: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DataQualityIssue:
        return DataQualityIssue(
            code=code,
            severity=severity,
            message=message,
            source_provider=batch.source.provider,
            symbol=batch.query.symbol,
            horizon=batch.query.horizon,
            timestamp=timestamp,
            metadata=metadata or {},
        )


def _quality_score(issues: list[DataQualityIssue]) -> float:
    score = 100.0
    for issue in issues:
        if issue.severity == "critical":
            score -= 40
        elif issue.severity == "warning":
            score -= 10
        else:
            score -= 2
    return max(score, 0.0)


def _range_pct(candle: Candle) -> float:
    if candle.close <= 0:
        return 0
    return (candle.high - candle.low) / candle.close * 100


def _pct_deviation(value: float, reference: float) -> float:
    if reference <= 0:
        return 0
    return abs(value - reference) / reference * 100
