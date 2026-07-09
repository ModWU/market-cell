from __future__ import annotations

from datetime import datetime, timezone


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
