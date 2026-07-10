# MarketCell Contracts

This directory contains language-neutral contracts shared by all MarketCell runtimes.

Current contracts are split by runtime path:

- JSON Schema for analysis requests, reports, replayable analysis runs, and Cell execution plans.
- Protobuf for realtime market-data events.
- Parquet schema notes for historical and replayable candle storage.

Directory policy:

- `json_schema/analysis_request.schema.json`: external input accepted by the analysis runtime.
- `json_schema/analysis_report.schema.json`: stable report shape emitted by the analysis runtime.
- `json_schema/analysis_run.schema.json`: run metadata, input snapshots, formula versions, and data-source audit records.
- `json_schema/cell_execution_plan.schema.json`: DAG nodes, service bindings, runtime hints, and local/cluster execution fabric contract.
- `protobuf/market_data.proto`: realtime event contract for Rust hot-path producers and later services.
- `parquet/candle_schema.md`: batch candle storage contract for professional historical data and replay.

Future language modules must depend on these contracts instead of duplicating private data shapes.
