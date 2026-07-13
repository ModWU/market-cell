from __future__ import annotations

from collections import Counter, defaultdict

from market_cell.execution.models import CellRuntime, CellRuntimeSummary, CellRuntimeTrace


def summarize_runtime_traces(traces: list[CellRuntimeTrace]) -> list[CellRuntimeSummary]:
    grouped: dict[
        tuple[str, str, str | None, str | None, CellRuntime | None],
        list[CellRuntimeTrace],
    ] = defaultdict(list)
    for trace in traces:
        grouped[
            (
                trace.cell_id,
                trace.formula_version,
                trace.implementation_id,
                trace.service_id,
                trace.runtime,
            )
        ].append(trace)

    summaries = [_summarize_trace_group(key, group) for key, group in grouped.items()]
    return sorted(
        summaries,
        key=lambda item: (
            -item.failed_count,
            -item.p95_duration_ms,
            item.cell_id,
            item.formula_version,
            item.implementation_id or "",
            item.service_id or "",
            item.runtime or "",
        ),
    )


def _summarize_trace_group(
    key: tuple[str, str, str | None, str | None, CellRuntime | None],
    traces: list[CellRuntimeTrace],
) -> CellRuntimeSummary:
    cell_id, formula_version, implementation_id, service_id, runtime = key
    durations = sorted(max(trace.duration_ms, 0.0) for trace in traces)
    status_counts = Counter(trace.status for trace in traces)
    return CellRuntimeSummary(
        cell_id=cell_id,
        formula_version=formula_version,
        implementation_id=implementation_id,
        service_id=service_id,
        runtime=runtime,
        trace_count=len(traces),
        succeeded_count=status_counts.get("succeeded", 0),
        failed_count=status_counts.get("failed", 0),
        skipped_count=status_counts.get("skipped", 0),
        average_duration_ms=round(sum(durations) / len(durations), 6) if durations else 0.0,
        max_duration_ms=durations[-1] if durations else 0.0,
        min_duration_ms=durations[0] if durations else 0.0,
        p95_duration_ms=_percentile(durations, 0.95),
        error_count=sum(1 for trace in traces if trace.error),
        retry_count=sum(trace.retry_count for trace in traces),
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    index = int(round((len(values) - 1) * percentile))
    return values[min(max(index, 0), len(values) - 1)]
