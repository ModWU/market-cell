import math

from market_cell.models import AnalysisRequest


class ValidationError(ValueError):
    pass


def validate_request(request: AnalysisRequest) -> None:
    issues: list[str] = []

    if not request.target.strip():
        issues.append("target 不能为空")
    if not request.horizon.strip():
        issues.append("horizon 不能为空")
    if not request.candles:
        issues.append("candles 至少需要一条 K 线")

    seen_timestamps: set[str] = set()
    for index, candle in enumerate(request.candles):
        prefix = f"candles[{index}]"
        if not candle.timestamp:
            issues.append(f"{prefix}.timestamp 不能为空")
        elif candle.timestamp in seen_timestamps:
            issues.append(f"{prefix}.timestamp 不能重复")
        seen_timestamps.add(candle.timestamp)
        for field_name in ("open", "high", "low", "close", "volume"):
            value = getattr(candle, field_name)
            if not math.isfinite(value):
                issues.append(f"{prefix}.{field_name} 必须是有效数字")
        if candle.high < candle.low:
            issues.append(f"{prefix}.high 不能小于 low")
        if candle.open <= 0 or candle.close <= 0 or candle.high <= 0 or candle.low <= 0:
            issues.append(f"{prefix} 的价格必须大于 0")
        if candle.high < max(candle.open, candle.close):
            issues.append(f"{prefix}.high 不能小于 open/close")
        if candle.low > min(candle.open, candle.close):
            issues.append(f"{prefix}.low 不能大于 open/close")
        if candle.volume < 0:
            issues.append(f"{prefix}.volume 不能小于 0")

    for index, event in enumerate(request.events):
        prefix = f"events[{index}]"
        if not event.title.strip():
            issues.append(f"{prefix}.title 不能为空")
        if not event.category.strip():
            issues.append(f"{prefix}.category 不能为空")
        if not math.isfinite(event.sentiment) or not -1 <= event.sentiment <= 1:
            issues.append(f"{prefix}.sentiment 必须在 -1 到 1 之间")
        if not math.isfinite(event.impact) or not 0 <= event.impact <= 100:
            issues.append(f"{prefix}.impact 必须在 0 到 100 之间")
        if not math.isfinite(event.freshness) or not 0 <= event.freshness <= 100:
            issues.append(f"{prefix}.freshness 必须在 0 到 100 之间")

    if issues:
        raise ValidationError("; ".join(issues))
