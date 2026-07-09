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

Optional local storage extras:

```bash
python3 -m pip install -e 'packages/python[storage]'
```

Repository-level contracts live in `../../contracts/`.
