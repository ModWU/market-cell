from __future__ import annotations

import hashlib
import importlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_cell.data.cache import safe_path_part
from market_cell.data.sources import CandleBatch, CandleQuery, CandleSourceError, SourceProfile
from market_cell.models import Candle


CANDLE_STORAGE_SCHEMA_VERSION = "candle_parquet.v0.1"


class OptionalStorageDependencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandleRow:
    source_provider: str
    exchange: str
    symbol: str
    market_type: str
    interval: str
    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int | None
    quote_volume: float | None
    fetched_at_ms: int
    quality_flags: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def batch_to_candle_rows(batch: CandleBatch) -> list[CandleRow]:
    metadata = batch.metadata
    exchange = str(batch.query.venue or metadata.get("exchange") or "unknown")
    market_type = str(metadata.get("market_type") or "unknown")
    fetched_at_ms = timestamp_to_ms(batch.fetched_at)
    interval_ms = interval_to_millis(batch.query.horizon)
    rows: list[CandleRow] = []

    for candle in batch.candles:
        open_time_ms = timestamp_to_ms(candle.timestamp)
        close_time_ms = open_time_ms + interval_ms - 1 if interval_ms > 0 else open_time_ms
        rows.append(
            CandleRow(
                source_provider=batch.source.provider,
                exchange=exchange,
                symbol=batch.query.symbol,
                market_type=market_type,
                interval=batch.query.horizon,
                open_time_ms=open_time_ms,
                close_time_ms=close_time_ms,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
                trade_count=_optional_int(metadata.get("trade_count")),
                quote_volume=_optional_float(metadata.get("quote_volume")),
                fetched_at_ms=fetched_at_ms,
                quality_flags=_string_list(metadata.get("quality_flags", [])),
            )
        )

    return rows


def candle_from_row(row: dict[str, Any]) -> Candle:
    return Candle(
        timestamp=str(row["open_time_ms"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
    )


def partition_path(root: Path | str, row: CandleRow) -> Path:
    date = datetime.fromtimestamp(row.open_time_ms / 1000, timezone.utc).date().isoformat()
    return (
        Path(root)
        / f"provider={safe_path_part(row.source_provider)}"
        / f"exchange={safe_path_part(row.exchange)}"
        / f"market_type={safe_path_part(row.market_type)}"
        / f"symbol={safe_path_part(row.symbol)}"
        / f"interval={safe_path_part(row.interval)}"
        / f"date={date}"
    )


def timestamp_to_ms(value: str) -> int:
    text = str(value).strip()
    if not text:
        raise ValueError("timestamp is empty")
    if text.isdigit():
        number = int(text)
        return number if number > 10_000_000_000 else number * 1000

    normalized = text.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def interval_to_millis(interval: str) -> int:
    text = interval.strip()
    if len(text) < 2:
        return 0
    unit = text[-1]
    try:
        amount = int(text[:-1])
    except ValueError:
        return 0

    multipliers = {
        "m": 60_000,
        "h": 3_600_000,
        "d": 86_400_000,
        "w": 604_800_000,
    }
    return amount * multipliers.get(unit, 0)


class ParquetCandleStore:
    def __init__(self, root: Path | str = ".market_cell_cache/parquet/candles") -> None:
        self.root = Path(root)

    def save(self, batch: CandleBatch) -> list[Path]:
        pyarrow = _require_optional_module("pyarrow", "pyarrow")
        parquet = _require_optional_module("pyarrow.parquet", "pyarrow")
        rows = batch_to_candle_rows(batch)
        grouped: dict[Path, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[partition_path(self.root, row)].append(row.to_dict())

        written: list[Path] = []
        for directory, records in grouped.items():
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"batch-{_records_digest(records)}.parquet"
            table = pyarrow.Table.from_pylist(records)
            parquet.write_table(table, path)
            written.append(path)
        return written


class DuckDBCandleSource:
    profile = SourceProfile(
        provider="local_parquet_duckdb",
        tier="development",
        description="Local Parquet candle source queried through DuckDB for replay and research.",
    )

    def __init__(self, root: Path | str = ".market_cell_cache/parquet/candles") -> None:
        self.root = Path(root)

    def fetch_candles(self, query: CandleQuery) -> CandleBatch:
        duckdb = _require_optional_module("duckdb", "duckdb")
        if not self.root.exists():
            raise CandleSourceError(f"Parquet K 线目录不存在：{self.root}")
        glob = str(self.root / "**" / "*.parquet")
        sql = """
            SELECT open_time_ms, open, high, low, close, volume
            FROM read_parquet(?)
            WHERE symbol = ?
              AND interval = ?
              AND (? IS NULL OR exchange = ?)
            ORDER BY open_time_ms DESC
            LIMIT ?
        """
        try:
            with duckdb.connect(database=":memory:") as connection:
                rows = connection.execute(
                    sql,
                    [glob, query.symbol, query.horizon, query.venue, query.venue, max(query.limit, 1)],
                ).fetchall()
        except Exception as exc:
            raise CandleSourceError(f"DuckDB 查询 Parquet K 线失败：{exc}") from exc

        candles = [
            Candle(
                timestamp=str(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in reversed(rows)
        ]
        return CandleBatch(
            query=query,
            candles=candles,
            source=self.profile,
            metadata={"storage": "parquet", "query_engine": "duckdb", "root": str(self.root)},
        )


def _require_optional_module(module_name: str, package_name: str):
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise OptionalStorageDependencyError(
            f"需要安装可选依赖 `{package_name}` 才能启用该存储能力"
        ) from exc


def _records_digest(records: list[dict[str, Any]]) -> str:
    raw = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]
