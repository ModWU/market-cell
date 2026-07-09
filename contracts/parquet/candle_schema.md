# MarketCell Candle Parquet Schema v0.1

This contract defines the batch storage shape for closed OHLCV candles. It is the target format for professional historical data, exchange backfill, Rust realtime aggregation output, and Python replay analysis.

## Required Columns

| Column | Type | Required | Notes |
|---|---|---|---|
| `source_provider` | string | yes | Data vendor or connector name, for example `kaiko`, `coinapi`, `binance_ws`. |
| `exchange` | string | yes | Venue name after normalization. |
| `symbol` | string | yes | Provider-normalized symbol. |
| `market_type` | string | yes | `spot`, `perpetual_future`, `futures`, `index`, or `unknown`. |
| `interval` | string | yes | Candle interval such as `1m`, `5m`, `1h`, `1d`. |
| `open_time_ms` | int64 | yes | Inclusive candle open time in Unix milliseconds. |
| `close_time_ms` | int64 | yes | Inclusive or provider-native close time in Unix milliseconds. |
| `open` | double | yes | Open price. Must be positive. |
| `high` | double | yes | High price. Must be positive and greater than or equal to open, low, and close. |
| `low` | double | yes | Low price. Must be positive and lower than or equal to open, high, and close. |
| `close` | double | yes | Close price. Must be positive. |
| `volume` | double | yes | Base volume. Must be non-negative. |
| `trade_count` | int64 | no | Number of trades if the provider supplies it. |
| `quote_volume` | double | no | Quote volume if the provider supplies it. |
| `fetched_at_ms` | int64 | yes | Time the row was fetched, aggregated, or persisted. |
| `quality_flags` | list<string> | yes | Empty when clean; otherwise stable quality codes. |

## Partition Recommendation

```text
provider=<source_provider>/
exchange=<exchange>/
market_type=<market_type>/
symbol=<symbol>/
interval=<interval>/
date=<YYYY-MM-DD>/
```

The partition layout is optimized for replay, backtest windows, and cross-source comparisons. Python should read this through a storage adapter; Cells must not read Parquet directly.

## Quality Rules

- `open_time_ms` must be lower than `close_time_ms`.
- `(source_provider, exchange, symbol, market_type, interval, open_time_ms)` should be unique.
- Rows with gaps, duplicates, out-of-order arrival, cross-source deviation, or provider repair events must set `quality_flags`.
- Production analysis may choose to reject, down-weight, or annotate rows with non-empty `quality_flags`.

## Ownership

- Rust hot path may produce this schema for realtime candle aggregation.
- Python cold path may consume this schema for historical analysis and replay.
- Schema evolution must be additive until a new major contract version is introduced.
