from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from market_cell.events import utc_now_iso
from market_cell.data.quality import inspect_candles
from market_cell.models import Candle


SourceTier = Literal["professional", "exchange_direct", "development"]


class CandleSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandleQuery:
    symbol: str
    horizon: str
    limit: int = 200
    start: str | None = None
    end: str | None = None
    venue: str | None = None


@dataclass(frozen=True)
class SourceProfile:
    provider: str
    tier: SourceTier
    description: str
    supports_realtime: bool = False
    supports_history: bool = True
    requires_api_key: bool = False


@dataclass(frozen=True)
class CandleBatch:
    query: CandleQuery
    candles: list[Candle]
    source: SourceProfile
    fetched_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)


class CandleSource(Protocol):
    profile: SourceProfile

    def fetch_candles(self, query: CandleQuery) -> CandleBatch:
        ...


class FileCandleSource:
    profile = SourceProfile(
        provider="local_json",
        tier="development",
        description="Local JSON file source for deterministic tests and offline replay.",
    )

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def fetch_candles(self, query: CandleQuery) -> CandleBatch:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise CandleSourceError(f"无法读取本地 K 线文件：{self.path}") from exc

        candles = [Candle.from_dict(item) for item in data.get("candles", [])]
        if query.limit > 0:
            candles = candles[-query.limit :]
        return CandleBatch(
            query=query,
            candles=candles,
            source=self.profile,
            metadata={"path": str(self.path)},
        )


class MarketDataRouter:
    def __init__(self, sources: list[CandleSource]) -> None:
        if not sources:
            raise ValueError("至少需要一个 K 线数据源")
        self.sources = sources

    def fetch_candles(self, query: CandleQuery) -> CandleBatch:
        failures: list[str] = []
        for source in self.sources:
            try:
                batch = source.fetch_candles(query)
            except Exception as exc:
                failures.append(f"{source.profile.provider}: {exc}")
                continue
            quality_report = inspect_candles(batch.candles)
            if quality_report.is_usable:
                return batch
            failures.append(f"{source.profile.provider}: {', '.join(quality_report.issues)}")
        raise CandleSourceError("所有 K 线数据源都失败：" + "; ".join(failures))
