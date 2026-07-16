from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Literal, Protocol

from market_cell.events import utc_now_iso
from market_cell.execution.models import (
    CellRuntime,
    CellRuntimeTrace,
    RuntimeTraceStatus,
)
from market_cell.hashing import stable_json_hash


RUNTIME_SUMMARY_SNAPSHOT_SCHEMA_VERSION = "runtime_summary_snapshot.v1"
RUNTIME_SUMMARY_WRITE_SCHEMA_VERSION = "runtime_summary_write.v1"

RuntimeSummaryWriteStatus = Literal["disabled", "succeeded", "failed"]


class RuntimeSummaryStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeSummaryEntry:
    cell_id: str
    formula_version: str
    implementation_id: str | None
    service_id: str | None
    runtime: CellRuntime | None
    trace_count: int
    run_count: int
    succeeded_count: int
    failed_count: int
    skipped_count: int
    retried_trace_count: int
    failure_rate: float
    retry_rate: float
    average_duration_ms: float
    max_duration_ms: float
    min_duration_ms: float
    p50_duration_ms: float
    p95_duration_ms: float
    p99_duration_ms: float
    error_count: int
    retry_count: int
    latest_status: RuntimeTraceStatus
    latest_finished_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeSummarySnapshot:
    snapshot_id: str
    store: str
    window_started_at: str
    window_ended_at: str
    generated_at: str
    trace_count: int
    entries: list[RuntimeSummaryEntry]
    schema_version: str = RUNTIME_SUMMARY_SNAPSHOT_SCHEMA_VERSION

    @classmethod
    def empty(
        cls,
        *,
        window: timedelta,
        as_of: datetime | None = None,
        store: str = "disabled",
    ) -> "RuntimeSummarySnapshot":
        return build_runtime_summary_snapshot(
            [],
            window=window,
            as_of=as_of,
            store=store,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "store": self.store,
            "window_started_at": self.window_started_at,
            "window_ended_at": self.window_ended_at,
            "generated_at": self.generated_at,
            "trace_count": self.trace_count,
            "entries": [entry.to_dict() for entry in self.entries],
            "schema_version": self.schema_version,
        }

    def to_run_metadata(self) -> dict[str, Any]:
        return {"runtime_summary_snapshot": self.to_dict()}


@dataclass(frozen=True)
class RuntimeSummaryWriteRecord:
    store: str
    status: RuntimeSummaryWriteStatus
    attempted_trace_count: int
    stored_trace_count: int
    duplicate_trace_count: int
    recorded_at: str
    error: str | None = None
    schema_version: str = RUNTIME_SUMMARY_WRITE_SCHEMA_VERSION

    @classmethod
    def disabled(cls, trace_count: int) -> "RuntimeSummaryWriteRecord":
        return cls(
            store="disabled",
            status="disabled",
            attempted_trace_count=trace_count,
            stored_trace_count=0,
            duplicate_trace_count=0,
            recorded_at=utc_now_iso(),
        )

    @classmethod
    def failed(
        cls,
        *,
        store: str,
        trace_count: int,
        error: Exception,
    ) -> "RuntimeSummaryWriteRecord":
        return cls(
            store=store,
            status="failed",
            attempted_trace_count=trace_count,
            stored_trace_count=0,
            duplicate_trace_count=0,
            recorded_at=utc_now_iso(),
            error=str(error),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_run_metadata(self) -> dict[str, Any]:
        return {"runtime_summary_write": self.to_dict()}


class RuntimeSummaryStore(Protocol):
    @property
    def name(self) -> str:
        ...

    def save_traces(
        self,
        traces: list[CellRuntimeTrace],
    ) -> RuntimeSummaryWriteRecord:
        ...

    def snapshot(
        self,
        *,
        window: timedelta,
        as_of: datetime | None = None,
    ) -> RuntimeSummarySnapshot:
        ...


class InMemoryRuntimeSummaryStore:
    def __init__(self) -> None:
        self._traces: dict[tuple[str, str], CellRuntimeTrace] = {}

    @property
    def name(self) -> str:
        return "in_memory_runtime_summary_store_v0.1"

    def save_traces(
        self,
        traces: list[CellRuntimeTrace],
    ) -> RuntimeSummaryWriteRecord:
        stored_count = 0
        duplicate_count = 0
        for trace in traces:
            _trace_finished_at(trace)
            key = (trace.run_id, trace.span_id)
            existing = self._traces.get(key)
            if existing is not None:
                if existing != trace:
                    raise RuntimeSummaryStoreError(
                        f"runtime trace identity collision for {trace.run_id}/{trace.span_id}"
                    )
                duplicate_count += 1
                continue
            self._traces[key] = trace
            stored_count += 1
        return RuntimeSummaryWriteRecord(
            store=self.name,
            status="succeeded",
            attempted_trace_count=len(traces),
            stored_trace_count=stored_count,
            duplicate_trace_count=duplicate_count,
            recorded_at=utc_now_iso(),
        )

    def snapshot(
        self,
        *,
        window: timedelta,
        as_of: datetime | None = None,
    ) -> RuntimeSummarySnapshot:
        return build_runtime_summary_snapshot(
            list(self._traces.values()),
            window=window,
            as_of=as_of,
            store=self.name,
        )


class FileSystemRuntimeSummaryStore:
    def __init__(
        self,
        root: Path | str = ".market_cell_cache/runtime_summaries",
    ) -> None:
        self.root = Path(root)

    @property
    def name(self) -> str:
        return "filesystem_runtime_summary_store_v0.1"

    def save_traces(
        self,
        traces: list[CellRuntimeTrace],
    ) -> RuntimeSummaryWriteRecord:
        pending: dict[Path, CellRuntimeTrace] = {}
        duplicate_count = 0
        for trace in traces:
            path = self._path_for(trace)
            pending_trace = pending.get(path)
            if pending_trace is not None:
                if pending_trace != trace:
                    raise RuntimeSummaryStoreError(
                        f"runtime trace identity collision for {trace.run_id}/{trace.span_id}"
                    )
                duplicate_count += 1
                continue
            if path.exists():
                existing = CellRuntimeTrace(**json.loads(path.read_text(encoding="utf-8")))
                if existing != trace:
                    raise RuntimeSummaryStoreError(
                        f"runtime trace identity collision for {trace.run_id}/{trace.span_id}"
                    )
                duplicate_count += 1
                continue
            pending[path] = trace

        for path, trace in pending.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    trace.to_dict(),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        return RuntimeSummaryWriteRecord(
            store=self.name,
            status="succeeded",
            attempted_trace_count=len(traces),
            stored_trace_count=len(pending),
            duplicate_trace_count=duplicate_count,
            recorded_at=utc_now_iso(),
        )

    def snapshot(
        self,
        *,
        window: timedelta,
        as_of: datetime | None = None,
    ) -> RuntimeSummarySnapshot:
        traces = (
            [
                CellRuntimeTrace(**json.loads(path.read_text(encoding="utf-8")))
                for path in sorted(self.root.glob("**/*.json"))
            ]
            if self.root.exists()
            else []
        )
        return build_runtime_summary_snapshot(
            traces,
            window=window,
            as_of=as_of,
            store=self.name,
        )

    def _path_for(self, trace: CellRuntimeTrace) -> Path:
        finished_at = _trace_finished_at(trace)
        return (
            self.root
            / f"cell={_safe_path_part(trace.cell_id)}"
            / f"formula={_safe_path_part(trace.formula_version)}"
            / f"implementation={_safe_path_part(trace.implementation_id)}"
            / f"service={_safe_path_part(trace.service_id)}"
            / f"runtime={_safe_path_part(trace.runtime)}"
            / f"date={finished_at.date().isoformat()}"
            / f"{_safe_path_part(trace.run_id)}-{_safe_path_part(trace.span_id)}.json"
        )


def build_runtime_summary_snapshot(
    traces: list[CellRuntimeTrace],
    *,
    window: timedelta,
    as_of: datetime | None = None,
    store: str,
) -> RuntimeSummarySnapshot:
    if window.total_seconds() <= 0:
        raise ValueError("runtime summary window must be positive")
    window_ended_at = _as_utc(as_of or datetime.now(timezone.utc))
    window_started_at = window_ended_at - window
    included = [
        trace
        for trace in traces
        if window_started_at <= _trace_finished_at(trace) <= window_ended_at
    ]
    grouped: dict[
        tuple[str, str, str | None, str | None, CellRuntime | None],
        list[CellRuntimeTrace],
    ] = defaultdict(list)
    for trace in included:
        grouped[
            (
                trace.cell_id,
                trace.formula_version,
                trace.implementation_id,
                trace.service_id,
                trace.runtime,
            )
        ].append(trace)
    entries = sorted(
        (_runtime_summary_entry(key, group) for key, group in grouped.items()),
        key=lambda entry: (
            entry.cell_id,
            entry.formula_version,
            entry.implementation_id or "",
            entry.service_id or "",
            entry.runtime or "",
        ),
    )
    generated_at = window_ended_at.isoformat()
    payload = {
        "store": store,
        "window_started_at": window_started_at.isoformat(),
        "window_ended_at": generated_at,
        "generated_at": generated_at,
        "trace_count": len(included),
        "entries": [entry.to_dict() for entry in entries],
        "schema_version": RUNTIME_SUMMARY_SNAPSHOT_SCHEMA_VERSION,
    }
    return RuntimeSummarySnapshot(
        snapshot_id=stable_json_hash(payload),
        store=store,
        window_started_at=payload["window_started_at"],
        window_ended_at=payload["window_ended_at"],
        generated_at=payload["generated_at"],
        trace_count=payload["trace_count"],
        entries=entries,
    )


def _runtime_summary_entry(
    key: tuple[str, str, str | None, str | None, CellRuntime | None],
    traces: list[CellRuntimeTrace],
) -> RuntimeSummaryEntry:
    cell_id, formula_version, implementation_id, service_id, runtime = key
    durations = sorted(max(trace.duration_ms, 0.0) for trace in traces)
    status_counts = Counter(trace.status for trace in traces)
    latest = max(
        traces,
        key=lambda trace: (_trace_finished_at(trace), trace.run_id, trace.span_id),
    )
    trace_count = len(traces)
    failed_count = status_counts.get("failed", 0)
    retried_trace_count = sum(1 for trace in traces if trace.retry_count > 0)
    return RuntimeSummaryEntry(
        cell_id=cell_id,
        formula_version=formula_version,
        implementation_id=implementation_id,
        service_id=service_id,
        runtime=runtime,
        trace_count=trace_count,
        run_count=len({trace.run_id for trace in traces}),
        succeeded_count=status_counts.get("succeeded", 0),
        failed_count=failed_count,
        skipped_count=status_counts.get("skipped", 0),
        retried_trace_count=retried_trace_count,
        failure_rate=round(failed_count / trace_count, 6),
        retry_rate=round(retried_trace_count / trace_count, 6),
        average_duration_ms=round(sum(durations) / trace_count, 6),
        max_duration_ms=durations[-1],
        min_duration_ms=durations[0],
        p50_duration_ms=_percentile(durations, 0.50),
        p95_duration_ms=_percentile(durations, 0.95),
        p99_duration_ms=_percentile(durations, 0.99),
        error_count=sum(1 for trace in traces if trace.error),
        retry_count=sum(trace.retry_count for trace in traces),
        latest_status=latest.status,
        latest_finished_at=latest.finished_at,
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = min(max(int(round((len(values) - 1) * percentile)), 0), len(values) - 1)
    return values[index]


def _trace_finished_at(trace: CellRuntimeTrace) -> datetime:
    try:
        return _parse_timestamp(trace.finished_at)
    except ValueError as exc:
        raise RuntimeSummaryStoreError(
            f"trace {trace.run_id}/{trace.span_id} has invalid finished_at"
        ) from exc


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_path_part(value: object) -> str:
    text = "unknown" if value is None else str(value)
    normalized = "".join(ch if ch.isalnum() else "_" for ch in text)
    return normalized.strip("_").lower() or "unknown"
