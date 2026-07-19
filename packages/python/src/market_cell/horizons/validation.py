from __future__ import annotations

from market_cell.data.timeframes import interval_to_millis, timestamp_to_ms
from market_cell.horizons.models import (
    MAXIMUM_HORIZON_COUNT,
    MINIMUM_HORIZON_COUNT,
    MULTI_HORIZON_REQUEST_SCHEMA_VERSION,
    MultiHorizonRequest,
)
from market_cell.validation import ValidationError, validate_request


def validate_multi_horizon_request(request: MultiHorizonRequest) -> None:
    issues: list[str] = []
    if request.schema_version != MULTI_HORIZON_REQUEST_SCHEMA_VERSION:
        issues.append(
            "schema_version 必须是 "
            f"{MULTI_HORIZON_REQUEST_SCHEMA_VERSION}"
        )
    if not request.target.strip():
        issues.append("target 不能为空")
    elif request.target != request.target.strip():
        issues.append("target 不能包含首尾空白")
    if request.as_of_ms < 0:
        issues.append("as_of_ms 不能小于 0")
    if not MINIMUM_HORIZON_COUNT <= len(request.requests) <= MAXIMUM_HORIZON_COUNT:
        issues.append(
            f"requests 数量必须在 {MINIMUM_HORIZON_COUNT} 到 "
            f"{MAXIMUM_HORIZON_COUNT} 之间"
        )

    horizon_names: list[str] = []
    horizon_durations: list[int] = []
    for index, child in enumerate(request.requests):
        prefix = f"requests[{index}]"
        try:
            validate_request(child)
        except ValidationError as exc:
            issues.append(f"{prefix}: {exc}")
        if child.target != request.target:
            issues.append(
                f"{prefix}.target 必须与多周期 target 完全一致"
            )
        if child.horizon != child.horizon.strip():
            issues.append(f"{prefix}.horizon 不能包含首尾空白")
        duration_ms = interval_to_millis(child.horizon)
        if duration_ms <= 0:
            issues.append(
                f"{prefix}.horizon 必须使用正整数加 s/m/h/d/w/M 单位"
            )
        horizon_names.append(child.horizon)
        horizon_durations.append(duration_ms)

        candle_times: list[int] = []
        for candle_index, candle in enumerate(child.candles):
            try:
                candle_times.append(timestamp_to_ms(candle.timestamp))
            except (TypeError, ValueError):
                issues.append(
                    f"{prefix}.candles[{candle_index}].timestamp "
                    "必须是可解析时间"
                )
        if len(candle_times) == len(child.candles) and candle_times:
            if any(
                current <= previous
                for previous, current in zip(candle_times, candle_times[1:])
            ):
                issues.append(
                    f"{prefix}.candles 必须按时间严格升序且时间点唯一"
                )
            latest_time_ms = candle_times[-1]
            if latest_time_ms > request.as_of_ms:
                issues.append(
                    f"{prefix} 最新 K 线不能晚于 as_of_ms"
                )
            elif duration_ms > 0 and request.as_of_ms - latest_time_ms > duration_ms:
                issues.append(
                    f"{prefix} 最新 K 线相对 as_of_ms 已超过一个周期"
                )

    if len(horizon_names) != len(set(horizon_names)):
        issues.append("requests.horizon 不能重复")
    positive_durations = [value for value in horizon_durations if value > 0]
    if len(positive_durations) == len(horizon_durations):
        if len(positive_durations) != len(set(positive_durations)):
            issues.append("等价周期不能通过不同字符串重复声明")
        if any(
            current <= previous
            for previous, current in zip(
                positive_durations,
                positive_durations[1:],
            )
        ):
            issues.append("requests 必须按周期从短到长排列")

    if issues:
        raise ValidationError("; ".join(issues))
