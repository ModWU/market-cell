# market-cell Python Runtime

This package contains the Python analysis runtime for MarketCell.

It owns:

- CLI entry points
- Analysis orchestration
- Cell registry and reference Cell implementations
- Versioned SupportResistanceCell formula with executable validation and false-positive guards
- Composed BreakoutCell confirmation over support/resistance structure, close quality, and bounded volume history
- Robust VolumePriceAnomalyCell baselines using bounded median/MAD statistics and positive-volume coverage guards, with anomaly evidence composed into ManipulationRiskCell
- Typed LiquidityCell analysis for near-book spread, 100bps quote depth, imbalance, concentration guards, and deterministic provenance quality
- Typed FundingOpenInterestCell analysis for normalized funding, robust open-interest change, synchronized mark-price alignment, cadence guards, and leverage-crowding risk
- Decision policies
- Report and run metadata handling
- Versioned replay comparison from saved inputs, complete decision-tree paths/hashes, formula versions, and Graph identity
- Typed multi-input composition with manifest declarations, node-scoped references, and CellInputBundle audits
- Versioned order-book snapshots and provider/venue provenance for replayable liquidity analysis
- Versioned funding/open-interest snapshots with explicit notional units, funding intervals, sampling cadence, synchronized mark prices, and replayable provenance
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
- CellRuntimeTrace records for per-Cell latency, routing failure, and actual service audits
- Local CellRuntimeSummary aggregation for service, Cell, formula, implementation, and runtime performance profiling
- Cross-run RuntimeSummaryStore snapshots with explicit windows, tail latency, failure/retry rates, and latest status
- Versioned fixed-input performance baselines with separate correctness and performance failures
- ServiceCapabilityCatalog contracts for one-Cell/many-service and one-service/many-Cell mappings
- Runtime-aware placement decisions with formula compatibility, failure-rate protection, deterministic priority, and P95 latency selection
- CellExecutor protocol, strict LocalCellExecutor, and deterministic ExecutorRouter reference implementations
- FailureControlledExecutor state machine for idempotent attempt identity, deadline rejection, retries, admission, cancellation, and plan-defined fallback
- Optional AnalysisEngine capability catalogs for mixed local and service-bound execution plans
- Plan/trace and CellResult contract validation at the execution boundary
- Failed AnalysisRun persistence with failure traces and summaries
- ExecutionPlan v5 primary/fallback binding identity, exact required-input binding, and deterministic DAG validation
- Deterministic CellRegistry resolution with duplicate local cell_id rejection

Execution code is split by responsibility:

- `graph/models.py`: stable Graph, node, and Organ data objects
- `graph/defaults.py`: stable default composition plus explicit order-book and derivatives-data graphs, independent of Registry order
- `graph/validation.py`: Graph, Organ, and registered-capability validation
- `graph/topology.py`: shared deterministic topology algorithms
- `execution/models.py`: stable execution data objects
- `execution/catalog.py`: service capability discovery model
- `execution/coordinator.py`: plan-driven topology execution and node state
- `execution/executor.py`: execution protocol, local runtime, and consistency checks
- `execution/router.py`: exact-service/runtime routing, dispatch failure traces, and delegated trace validation
- `execution/control.py`: attempt identity, failure classification, deadline, retry, admission, cancellation, and fallback state transitions
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
