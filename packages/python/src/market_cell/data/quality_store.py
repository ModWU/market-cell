from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from market_cell.data.cache import safe_path_part
from market_cell.data.monitoring import (
    DataQualityIssue,
    SourceComparisonReport,
    SourceQualityReport,
)
from market_cell.events import utc_now_iso


QualityRecordKind = Literal["source_quality", "source_comparison"]


@dataclass(frozen=True)
class DataQualityRecord:
    record_id: str
    kind: QualityRecordKind
    observed_at: str
    issue: DataQualityIssue
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "kind": self.kind,
            "observed_at": self.observed_at,
            "issue": self.issue.to_dict(),
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DataQualityRecord":
        return cls(
            record_id=str(data["record_id"]),
            kind=data["kind"],
            observed_at=str(data["observed_at"]),
            issue=DataQualityIssue(**data["issue"]),
            context=dict(data.get("context", {})),
        )


class DataQualityStore(Protocol):
    def save_issue(
        self,
        issue: DataQualityIssue,
        *,
        kind: QualityRecordKind = "source_quality",
        observed_at: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> DataQualityRecord:
        ...

    def list_records(
        self,
        *,
        source_provider: str | None = None,
        symbol: str | None = None,
        code: str | None = None,
        severity: str | None = None,
    ) -> list[DataQualityRecord]:
        ...


class FileSystemDataQualityStore:
    def __init__(self, root: Path | str = ".market_cell_cache/data_quality") -> None:
        self.root = Path(root)

    def save_issue(
        self,
        issue: DataQualityIssue,
        *,
        kind: QualityRecordKind = "source_quality",
        observed_at: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> DataQualityRecord:
        timestamp = observed_at or utc_now_iso()
        record = DataQualityRecord(
            record_id=_record_id(kind, timestamp, issue, context or {}),
            kind=kind,
            observed_at=timestamp,
            issue=issue,
            context=context or {},
        )
        path = self._path_for(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def save_source_report(
        self,
        report: SourceQualityReport,
        *,
        observed_at: str | None = None,
    ) -> list[DataQualityRecord]:
        context = {
            "quality_score": report.quality_score,
            "is_usable": report.is_usable,
        }
        return [
            self.save_issue(issue, kind="source_quality", observed_at=observed_at, context=context)
            for issue in report.issues
        ]

    def save_comparison_report(
        self,
        report: SourceComparisonReport,
        *,
        observed_at: str | None = None,
    ) -> list[DataQualityRecord]:
        context = {
            "primary_provider": report.primary_provider,
            "reference_provider": report.reference_provider,
            "max_close_deviation_pct": report.max_close_deviation_pct,
            "is_usable": report.is_usable,
        }
        return [
            self.save_issue(issue, kind="source_comparison", observed_at=observed_at, context=context)
            for issue in report.issues
        ]

    def list_records(
        self,
        *,
        source_provider: str | None = None,
        symbol: str | None = None,
        code: str | None = None,
        severity: str | None = None,
    ) -> list[DataQualityRecord]:
        if not self.root.exists():
            return []

        records: list[DataQualityRecord] = []
        for path in sorted(self.root.glob("**/*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = DataQualityRecord.from_dict(json.loads(line))
                if source_provider is not None and record.issue.source_provider != source_provider:
                    continue
                if symbol is not None and record.issue.symbol != symbol:
                    continue
                if code is not None and record.issue.code != code:
                    continue
                if severity is not None and record.issue.severity != severity:
                    continue
                records.append(record)
        return records

    def _path_for(self, record: DataQualityRecord) -> Path:
        issue = record.issue
        date = _date_part(record.observed_at)
        return (
            self.root
            / f"provider={safe_path_part(issue.source_provider)}"
            / f"symbol={safe_path_part(issue.symbol)}"
            / f"horizon={safe_path_part(issue.horizon)}"
            / f"date={date}"
            / "issues.jsonl"
        )


def _record_id(
    kind: QualityRecordKind,
    observed_at: str,
    issue: DataQualityIssue,
    context: dict[str, Any],
) -> str:
    payload = {
        "kind": kind,
        "observed_at": observed_at,
        "issue": issue.to_dict(),
        "context": context,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _date_part(value: str) -> str:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return "unknown"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date().isoformat()
