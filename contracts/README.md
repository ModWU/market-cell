# MarketCell Contracts

This directory contains language-neutral contracts shared by all MarketCell runtimes.

Current contracts are split by runtime path:

- JSON Schema for analysis requests, reports, replayable analysis runs, Cell execution plans, service capability catalogs, placement decisions, Cell runtime traces, and Cell runtime summaries.
- Protobuf for realtime market-data events.
- Parquet schema notes for historical and replayable candle storage.

Directory policy:

- `json_schema/analysis_request.schema.json`: external input accepted by the analysis runtime.
- `json_schema/analysis_report.schema.json`: stable report shape emitted by the analysis runtime.
- `json_schema/analysis_run.schema.json`: run metadata, input snapshots, formula versions, and data-source audit records.
- `json_schema/cell_graph_definition.schema.json`: versioned Cell composition DAG and overlapping named Organ subgraphs without service location.
- `json_schema/cell_graph_validation.schema.json`: structured graph, Organ, dependency, reachability, and registered-capability validation failures.
- `json_schema/cell_execution_plan.schema.json`: v2 DAG contract with unique node identities and explicit binding references.
- `json_schema/cell_service_binding.schema.json`: shared implementation-to-service binding with deterministic `binding_id`.
- `json_schema/service_capability_catalog.schema.json`: language-neutral catalog of the Cell implementations currently provided by local or remote services.
- `json_schema/cell_placement_decision.schema.json`: auditable selection record for the implementation and service chosen for each Cell.
- `json_schema/execution_plan_validation.schema.json`: structured DAG, root, dependency, binding, cycle, and reachability validation failures.
- `json_schema/plan_execution.schema.json`: coordinator, node execution order, completed nodes, and failed-node audit for one validated plan run.
- `json_schema/cell_runtime_trace.schema.json`: per-Cell execution trace records for latency, errors, retry count, and service attribution.
- `json_schema/cell_runtime_summary.schema.json`: per-run aggregated runtime profile grouped by Cell, formula version, implementation, service, and runtime.
- `protobuf/market_data.proto`: realtime event contract for Rust hot-path producers and later services.
- `parquet/candle_schema.md`: batch candle storage contract for professional historical data and replay.

Future language modules must depend on these contracts instead of duplicating private data shapes.

Current execution contracts use CellExecutionPlan v2, ServiceCapabilityCatalog v2, and CellPlacementDecision v2. AnalysisRun v1 still accepts stored CellExecutionPlan v1 metadata for replay compatibility.
