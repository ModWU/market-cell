from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from market_cell.data.quality_store import DataQualityRecord


HealthGrade = Literal["excellent", "good", "degraded", "poor"]
TrendWindow = Literal["hour", "day"]


@dataclass(frozen=True)
class SourceHealthSummary:
    source_provider: str
    symbol: str
    horizon: str
    record_count: int
    health_score: float
    health_grade: HealthGrade
    severity_counts: dict[str, int] = field(default_factory=dict)
    issue_counts: dict[str, int] = field(default_factory=dict)
    first_observed_at: str | None = None
    last_observed_at: str | None = None
    dominant_issue_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceHealthTrendPoint:
    source_provider: str
    symbol: str
    horizon: str
    window: TrendWindow
    window_start: str
    record_count: int
    health_score: float
    health_grade: HealthGrade
    severity_counts: dict[str, int] = field(default_factory=dict)
    issue_counts: dict[str, int] = field(default_factory=dict)
    dominant_issue_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderReliabilitySummary:
    source_provider: str
    trend_point_count: int
    record_count: int
    average_health_score: float
    latest_health_score: float
    worst_health_score: float
    health_grade: HealthGrade
    affected_symbols: list[str] = field(default_factory=list)
    affected_horizons: list[str] = field(default_factory=list)
    severity_counts: dict[str, int] = field(default_factory=dict)
    issue_counts: dict[str, int] = field(default_factory=dict)
    first_window_start: str | None = None
    last_window_start: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_quality_records(records: list[DataQualityRecord]) -> list[SourceHealthSummary]:
    grouped: dict[tuple[str, str, str], list[DataQualityRecord]] = defaultdict(list)
    for record in records:
        issue = record.issue
        grouped[(issue.source_provider, issue.symbol, issue.horizon)].append(record)

    summaries = [_summarize_group(key, group) for key, group in grouped.items()]
    return sorted(
        summaries,
        key=lambda item: (item.health_score, item.source_provider, item.symbol, item.horizon),
    )


def rank_source_health(summaries: list[SourceHealthSummary]) -> list[SourceHealthSummary]:
    return sorted(
        summaries,
        key=lambda item: (-item.health_score, item.record_count, item.source_provider, item.symbol, item.horizon),
    )


def build_health_trends(
    records: list[DataQualityRecord],
    window: TrendWindow = "day",
) -> list[SourceHealthTrendPoint]:
    if window not in ("hour", "day"):
        raise ValueError("window must be 'hour' or 'day'")

    grouped: dict[tuple[str, str, str, str], list[DataQualityRecord]] = defaultdict(list)
    for record in records:
        issue = record.issue
        grouped[(issue.source_provider, issue.symbol, issue.horizon, _window_start(record.observed_at, window))].append(
            record
        )

    points = [_trend_point(key, group, window) for key, group in grouped.items()]
    return sorted(points, key=lambda item: (item.window_start, item.source_provider, item.symbol, item.horizon))


def summarize_provider_reliability(
    records: list[DataQualityRecord],
    window: TrendWindow = "day",
) -> list[ProviderReliabilitySummary]:
    trend_points = build_health_trends(records, window=window)
    grouped: dict[str, list[SourceHealthTrendPoint]] = defaultdict(list)
    for point in trend_points:
        grouped[point.source_provider].append(point)

    summaries = [_provider_reliability(provider, points) for provider, points in grouped.items()]
    return rank_provider_reliability(summaries)


def rank_provider_reliability(
    summaries: list[ProviderReliabilitySummary],
) -> list[ProviderReliabilitySummary]:
    return sorted(
        summaries,
        key=lambda item: (
            -item.average_health_score,
            -item.latest_health_score,
            -item.worst_health_score,
            item.record_count,
            item.source_provider,
        ),
    )


def _summarize_group(
    key: tuple[str, str, str],
    records: list[DataQualityRecord],
) -> SourceHealthSummary:
    source_provider, symbol, horizon = key
    severity_counter = Counter(record.issue.severity for record in records)
    issue_counter = Counter(record.issue.code for record in records)
    score = _health_score(severity_counter)
    observed = sorted(record.observed_at for record in records)

    return SourceHealthSummary(
        source_provider=source_provider,
        symbol=symbol,
        horizon=horizon,
        record_count=len(records),
        health_score=score,
        health_grade=_health_grade(score),
        severity_counts=dict(sorted(severity_counter.items())),
        issue_counts=dict(sorted(issue_counter.items())),
        first_observed_at=observed[0] if observed else None,
        last_observed_at=observed[-1] if observed else None,
        dominant_issue_codes=_dominant_issue_codes(issue_counter),
    )


def _trend_point(
    key: tuple[str, str, str, str],
    records: list[DataQualityRecord],
    window: TrendWindow,
) -> SourceHealthTrendPoint:
    source_provider, symbol, horizon, window_start = key
    severity_counter = Counter(record.issue.severity for record in records)
    issue_counter = Counter(record.issue.code for record in records)
    score = _health_score(severity_counter)

    return SourceHealthTrendPoint(
        source_provider=source_provider,
        symbol=symbol,
        horizon=horizon,
        window=window,
        window_start=window_start,
        record_count=len(records),
        health_score=score,
        health_grade=_health_grade(score),
        severity_counts=dict(sorted(severity_counter.items())),
        issue_counts=dict(sorted(issue_counter.items())),
        dominant_issue_codes=_dominant_issue_codes(issue_counter),
    )


def _provider_reliability(
    source_provider: str,
    points: list[SourceHealthTrendPoint],
) -> ProviderReliabilitySummary:
    ordered = sorted(points, key=lambda item: item.window_start)
    severity_counter: Counter[str] = Counter()
    issue_counter: Counter[str] = Counter()
    for point in ordered:
        severity_counter.update(point.severity_counts)
        issue_counter.update(point.issue_counts)

    average_score = sum(point.health_score for point in ordered) / len(ordered) if ordered else 100.0
    latest_score = ordered[-1].health_score if ordered else 100.0
    worst_score = min((point.health_score for point in ordered), default=100.0)

    return ProviderReliabilitySummary(
        source_provider=source_provider,
        trend_point_count=len(ordered),
        record_count=sum(point.record_count for point in ordered),
        average_health_score=round(average_score, 6),
        latest_health_score=latest_score,
        worst_health_score=worst_score,
        health_grade=_health_grade(average_score),
        affected_symbols=sorted({point.symbol for point in ordered}),
        affected_horizons=sorted({point.horizon for point in ordered}),
        severity_counts=dict(sorted(severity_counter.items())),
        issue_counts=dict(sorted(issue_counter.items())),
        first_window_start=ordered[0].window_start if ordered else None,
        last_window_start=ordered[-1].window_start if ordered else None,
    )


def _health_score(severity_counts: Counter[str]) -> float:
    penalty = (
        severity_counts.get("critical", 0) * 20
        + severity_counts.get("warning", 0) * 5
        + severity_counts.get("info", 0) * 1
    )
    return max(100.0 - penalty, 0.0)


def _health_grade(score: float) -> HealthGrade:
    if score >= 95:
        return "excellent"
    if score >= 85:
        return "good"
    if score >= 70:
        return "degraded"
    return "poor"


def _dominant_issue_codes(issue_counts: Counter[str]) -> list[str]:
    return [
        code
        for code, _count in sorted(
            issue_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:3]
    ]


def _window_start(value: str, window: TrendWindow) -> str:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return "unknown"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    utc = parsed.astimezone(timezone.utc)
    if window == "hour":
        return utc.replace(minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")
    return utc.date().isoformat()
