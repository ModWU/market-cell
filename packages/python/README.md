# market-cell Python Runtime

This package contains the Python analysis runtime for MarketCell.

It owns:

- CLI entry points
- Analysis orchestration
- Cell registry and reference Cell implementations
- Decision policies
- Report and run metadata handling
- Replay comparison from saved input snapshots, formula versions, and Graph identity
- Static and low-frequency data analysis workflows
- Candle source quality monitoring and cross-source comparison
- Data quality issue persistence for source health history
- Source health summaries by provider, symbol, and horizon
- Source health trends and provider reliability summaries
- Provider selection plans for primary, backup, and disabled market data sources
- Auditable router plans that map provider selection plans to concrete candle sources
- Run metadata persistence for provider selection and router plan audits
- AnalysisRun schema versioning for replayable run records
- Mandatory local CellExecutionPlan generation and validation
- Versioned CellGraphDefinition and overlapping named Organ subgraphs
- Graph validation for topology, Organ closure, reachability, and Registry compatibility
- Plan-driven local DAG coordination with node-scoped results and dependency ordering
- Versioned PlanExecution audit metadata for completed and failed runs
- Local CellRuntimeTrace records for per-Cell latency and status audits
- Local CellRuntimeSummary aggregation for service, Cell, formula, implementation, and runtime performance profiling
- Cross-run RuntimeSummaryStore snapshots with explicit windows, tail latency, failure/retry rates, and latest status
- Versioned fixed-input performance baselines with separate correctness and performance failures
- ServiceCapabilityCatalog contracts for one-Cell/many-service and one-service/many-Cell mappings
- Runtime-aware placement decisions with formula compatibility, failure-rate protection, deterministic priority, and P95 latency selection
- CellExecutor protocol and strict LocalCellExecutor reference implementation
- Plan/trace and CellResult contract validation at the execution boundary
- Failed AnalysisRun persistence with failure traces and summaries
- ExecutionPlan v2 node/binding identity and deterministic DAG validation
- Deterministic CellRegistry resolution with duplicate local cell_id rejection

Execution code is split by responsibility:

- `graph/models.py`: stable Graph, node, and Organ data objects
- `graph/defaults.py`: reference analysis composition independent of Registry order
- `graph/validation.py`: Graph, Organ, and registered-capability validation
- `graph/topology.py`: shared deterministic topology algorithms
- `execution/models.py`: stable execution data objects
- `execution/catalog.py`: service capability discovery model
- `execution/coordinator.py`: plan-driven topology execution and node state
- `execution/executor.py`: execution protocol, local runtime, and consistency checks
- `execution/placement.py`: implementation selection policy and audit decisions
- `execution/planner.py`: Cell DAG and binding plan generation
- `execution/plan_validation.py`: structural, binding, cycle, reachability, and topology validation
- `execution/telemetry.py`: runtime trace aggregation
- `execution/runtime_store.py`: idempotent cross-run trace storage and placement history snapshots
- `performance.py`: fixed-input benchmark runner, duration distributions, and regression classification

Optional local storage extras:

```bash
python3 -m pip install -e 'packages/python[storage]'
```

Repository-level contracts live in `../../contracts/`.
