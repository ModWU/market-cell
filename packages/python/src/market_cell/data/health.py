from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from market_cell.data.quality_store import DataQualityRecord


HealthGrade = Literal["excellent", "good", "degraded", "poor"]


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
