from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from market_cell.models import Candle
from market_cell.scoring import clamp


FEATURE_VERSION = "market_features_v0.1"
FEATURE_SNAPSHOT_SCHEMA_VERSION = "feature_snapshot.v1"


@dataclass(frozen=True)
class FeatureSnapshot:
    candle_count: int
    first_close: float | None
    last_close: float | None
    close_change_pct: float
    latest_close_change: float
    previous_average_volume: float
    latest_volume_ratio: float
    average_range_pct: float
    latest_range_pct: float
    latest_wick_ratio: float
    total_move_pct: float
    path_distance_pct: float
    trend_efficiency: float
    feature_version: str = FEATURE_VERSION
    source_input_hash: str | None = None
    schema_version: str = FEATURE_SNAPSHOT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_feature_snapshot(
    candles: list[Candle],
    source_input_hash: str | None = None,
) -> FeatureSnapshot:
    candle_count = len(candles)
    if not candles:
        return FeatureSnapshot(
            candle_count=0,
            first_close=None,
            last_close=None,
            close_change_pct=0,
            latest_close_change=0,
            previous_average_volume=0,
            latest_volume_ratio=1,
            average_range_pct=0,
            latest_range_pct=0,
            latest_wick_ratio=0,
            total_move_pct=0,
            path_distance_pct=0,
            trend_efficiency=0,
            source_input_hash=source_input_hash,
        )

    first = candles[0]
    latest = candles[-1]
    previous = candles[:-1]
    first_close = first.close
    last_close = latest.close
    close_change_pct = ((last_close - first_close) / first_close * 100) if first_close else 0
    latest_close_change = latest.close - candles[-2].close if candle_count >= 2 else 0
    previous_average_volume = sum(item.volume for item in previous) / len(previous) if previous else 0
    latest_volume_ratio = latest.volume / previous_average_volume if previous_average_volume else 1

    ranges = [(item.high - item.low) / item.close * 100 for item in candles if item.close]
    average_range_pct = sum(ranges) / len(ranges) if ranges else 0
    latest_range_pct = (latest.high - latest.low) / latest.close * 100 if latest.close else 0

    latest_body = abs(latest.close - latest.open)
    latest_range_abs = latest.high - latest.low
    latest_wick_total = max(latest_range_abs - latest_body, 0)
    latest_wick_ratio = latest_wick_total / latest_range_abs if latest_range_abs else 0

    closes = [item.close for item in candles]
    step_moves = [
        abs((current - previous_close) / previous_close * 100)
        for previous_close, current in zip(closes, closes[1:])
        if previous_close
    ]
    path_distance_pct = sum(step_moves)
    trend_efficiency = clamp(abs(close_change_pct) / path_distance_pct, maximum=1.0) if path_distance_pct else 0

    return FeatureSnapshot(
        candle_count=candle_count,
        first_close=first_close,
        last_close=last_close,
        close_change_pct=close_change_pct,
        latest_close_change=latest_close_change,
        previous_average_volume=previous_average_volume,
        latest_volume_ratio=latest_volume_ratio,
        average_range_pct=average_range_pct,
        latest_range_pct=latest_range_pct,
        latest_wick_ratio=latest_wick_ratio,
        total_move_pct=close_change_pct,
        path_distance_pct=path_distance_pct,
        trend_efficiency=trend_efficiency,
        source_input_hash=source_input_hash,
    )
