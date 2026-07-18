# MarketCell Contracts

This directory contains language-neutral contracts shared by all MarketCell runtimes.

Current contracts are split by runtime path:

- JSON Schema for analysis requests, reports, replayable multi-input analysis runs, replay comparisons, input snapshots and references, typed Cell input bundles, order-book snapshots, funding/open-interest snapshots, data provenance, feature snapshots, Cell execution plans, service capability catalogs, placement decisions, execution-control records, Cell runtime traces, and Cell runtime summaries.
- Protobuf for realtime market-data events.
- Parquet schema notes for historical and replayable candle storage.

Directory policy:

- `json_schema/analysis_request.schema.json`: external input accepted by the analysis runtime.
- `json_schema/analysis_report.schema.json`: stable report shape emitted by the analysis runtime.
- `json_schema/analysis_run.schema.json`: run metadata, input snapshots, formula versions, and data-source audit records.
- `json_schema/replay_comparison.schema.json`: input identity, complete decision-tree drift paths and hashes, formula drift, and Graph drift for one replay.
- `json_schema/input_snapshot.schema.json`: immutable logical input payload with content hash, provenance, data version, and size.
- `json_schema/input_snapshot_audit.schema.json`: payload-free InputSnapshot metadata persisted with an AnalysisRun.
- `json_schema/input_reference.schema.json`: lightweight resolver address and integrity envelope carried by an execution plan.
- `json_schema/input_resolution_record.schema.json`: per-node resolver status, cache use, provenance, and hash audit.
- `json_schema/cell_input_bundle.schema.json`: payload-free audit shape for the exact typed inputs composed for one node.
- `json_schema/data_provenance.schema.json`: provider, venue, market type, event/fetch time, sequence, source identity, and quality flags.
- `json_schema/order_book_snapshot.schema.json`: sorted bid/ask depth payload backed by versioned provenance.
- `json_schema/funding_open_interest_snapshot.schema.json`: synchronized funding-rate, open-interest-notional, and mark-price series with explicit intervals and provenance.
- `json_schema/feature_snapshot.schema.json`: independently versioned reusable feature payload.
- `json_schema/cell_graph_definition.schema.json`: versioned Cell composition DAG and overlapping named Organ subgraphs without service location.
- `json_schema/cell_graph_validation.schema.json`: structured graph, Organ, dependency, reachability, and registered-capability validation failures.
- `json_schema/cell_execution_plan.schema.json`: v5 DAG contract with unique node identities, explicit primary/fallback bindings, required input kinds, and payload-free input references.
- `json_schema/cell_service_binding.schema.json`: shared implementation-to-service binding with deterministic `binding_id`.
- `json_schema/service_capability_catalog.schema.json`: language-neutral catalog of the Cell implementations currently provided by local or remote services.
- `json_schema/cell_placement_decision.schema.json`: auditable selection record for the implementation and service chosen for each Cell.
- `json_schema/execution_plan_validation.schema.json`: structured DAG, root, dependency, binding, cycle, and reachability validation failures.
- `json_schema/plan_execution.schema.json`: coordinator, node execution order, completed nodes, and failed-node audit for one validated plan run.
- `json_schema/execution_control_record.schema.json`: per-node attempt, idempotency, retry, timeout, backpressure, cancellation, fallback, and terminal-status audit.
- `json_schema/cell_runtime_trace.schema.json`: per-Cell execution trace records for latency, errors, retry count, and service attribution.
- `json_schema/cell_runtime_summary.schema.json`: per-run aggregated runtime profile grouped by Cell, formula version, implementation, service, and runtime.
- `json_schema/runtime_summary_snapshot.schema.json`: explicit cross-run time-window snapshot with sample counts, tail latency, failure/retry rates, and latest status.
- `json_schema/runtime_summary_write.schema.json`: idempotent runtime-history persistence result for one AnalysisRun.
- `json_schema/performance_baseline.schema.json`: versioned fixed-input benchmark, expected result identity, reference measurement, and regression thresholds.
- `json_schema/performance_benchmark_result.schema.json`: total and per-node duration distributions with separate correctness and performance failures.
- `protobuf/market_data.proto`: realtime event contract for Rust hot-path producers and later services.
- `parquet/candle_schema.md`: batch candle storage contract for professional historical data and replay.
- `test_vectors/input_identity_v1.json`: shared canonical JSON, content hash, payload size, snapshot identity, and reference identity vector for every language runtime.
- `test_vectors/execution_identity_v1.json`: shared idempotency-key and attempt-id identity vector for every executor runtime.
- `test_vectors/order_book_snapshot_v1.json`: shared order-book payload hash, size, snapshot identity, and reference identity vector.
- `test_vectors/funding_open_interest_snapshot_v1.json`: shared derivatives-positioning payload hash, size, snapshot identity, and reference identity vector.

Future language modules must depend on these contracts instead of duplicating private data shapes.

Current execution contracts use CellExecutionPlan v5, ServiceCapabilityCatalog v2, CellPlacementDecision v3, ExecutionControlRecord v1, CellInputBundle v1, AnalysisRun v2, and ReplayComparison v1. ReplayRunner still reads legacy AnalysisRun v1 records, while v2 metadata accepts stored CellExecutionPlan v1 through v5 for compatibility.
