from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from market_cell.data.sources import CandleBatch, CandleQuery, CandleSourceError, SourceProfile
from market_cell.models import Candle


BINANCE_INTERVALS = {
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "6h",
    "8h",
    "12h",
    "1d",
    "3d",
    "1w",
    "1M",
}


class BinanceSpotKlineSource:
    profile = SourceProfile(
        provider="binance_spot",
        tier="exchange_direct",
        description="Binance Spot public kline REST source for development, backfill, and cross-checking.",
        supports_history=True,
        requires_api_key=False,
    )

    def __init__(self, base_url: str = "https://api.binance.com", timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def fetch_candles(self, query: CandleQuery) -> CandleBatch:
        if query.horizon not in BINANCE_INTERVALS:
            raise CandleSourceError(f"Binance 不支持周期：{query.horizon}")

        params: dict[str, str | int] = {
            "symbol": normalize_binance_symbol(query.symbol),
            "interval": query.horizon,
            "limit": min(max(query.limit, 1), 1000),
        }
        if query.start is not None:
            params["startTime"] = query.start
        if query.end is not None:
            params["endTime"] = query.end

        url = f"{self.base_url}/api/v3/klines?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": "market-cell/0.1"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except OSError as exc:
            raise CandleSourceError(f"Binance K 线请求失败：{exc}") from exc

        if not isinstance(payload, list):
            raise CandleSourceError("Binance K 线响应格式异常")

        candles = [parse_binance_kline(item) for item in payload]
        return CandleBatch(
            query=query,
            candles=candles,
            source=self.profile,
            metadata={"url": url},
        )


def normalize_binance_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace("-", "").upper()


def parse_binance_kline(item: list) -> Candle:
    if len(item) < 6:
        raise CandleSourceError("Binance K 线条目字段不足")
    return Candle(
        timestamp=str(item[0]),
        open=float(item[1]),
        high=float(item[2]),
        low=float(item[3]),
        close=float(item[4]),
        volume=float(item[5]),
    )
