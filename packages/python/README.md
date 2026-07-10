# market-cell Python Runtime

This package contains the Python analysis runtime for MarketCell.

It owns:

- CLI entry points
- Analysis orchestration
- Cell registry and reference Cell implementations
- Decision policies
- Report and run metadata handling
- Replay comparison from saved input snapshots
- Static and low-frequency data analysis workflows
- Candle source quality monitoring and cross-source comparison
- Data quality issue persistence for source health history
- Source health summaries by provider, symbol, and horizon
- Source health trends and provider reliability summaries
- Provider selection plans for primary, backup, and disabled market data sources
- Auditable router plans that map provider selection plans to concrete candle sources
- Run metadata persistence for provider selection and router plan audits
- AnalysisRun schema versioning for replayable run records
- Local CellExecutionPlan generation for future service-fabric execution

Optional local storage extras:

```bash
python3 -m pip install -e 'packages/python[storage]'
```

Repository-level contracts live in `../../contracts/`.
