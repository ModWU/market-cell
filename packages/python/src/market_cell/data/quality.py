from __future__ import annotations

import math
from dataclasses import dataclass, field

from market_cell.models import Candle


@dataclass(frozen=True)
class CandleQualityReport:
    is_usable: bool
    issues: list[str] = field(default_factory=list)


def inspect_candles(candles: list[Candle]) -> CandleQualityReport:
    issues: list[str] = []
    if not candles:
        return CandleQualityReport(is_usable=False, issues=["candles empty"])

    seen_timestamps: set[str] = set()
    previous_timestamp: str | None = None
    for index, candle in enumerate(candles):
        prefix = f"candles[{index}]"
        if not candle.timestamp:
            issues.append(f"{prefix}.timestamp empty")
        if candle.timestamp in seen_timestamps:
            issues.append(f"{prefix}.timestamp duplicate")
        seen_timestamps.add(candle.timestamp)

        if previous_timestamp is not None and candle.timestamp < previous_timestamp:
            issues.append(f"{prefix}.timestamp out of order")
        previous_timestamp = candle.timestamp

        for field_name in ("open", "high", "low", "close", "volume"):
            value = getattr(candle, field_name)
            if not math.isfinite(value):
                issues.append(f"{prefix}.{field_name} invalid")

        if candle.open <= 0 or candle.high <= 0 or candle.low <= 0 or candle.close <= 0:
            issues.append(f"{prefix}.price non-positive")
        if candle.volume < 0:
            issues.append(f"{prefix}.volume negative")
        if candle.high < candle.low:
            issues.append(f"{prefix}.high lower than low")
        if candle.high < max(candle.open, candle.close):
            issues.append(f"{prefix}.high lower than open/close")
        if candle.low > min(candle.open, candle.close):
            issues.append(f"{prefix}.low higher than open/close")

    return CandleQualityReport(is_usable=not issues, issues=issues)
