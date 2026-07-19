from __future__ import annotations

from datetime import datetime, timezone
import re


CANONICAL_MONTH_MILLIS = 30 * 86_400_000
_INTERVAL_PATTERN = re.compile(r"^(?P<amount>[1-9][0-9]*)(?P<unit>[smhdwM])$")


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
    match = _INTERVAL_PATTERN.fullmatch(text)
    if match is None:
        return 0
    amount = int(match.group("amount"))
    unit = match.group("unit")

    multipliers = {
        "s": 1_000,
        "m": 60_000,
        "h": 3_600_000,
        "d": 86_400_000,
        "w": 604_800_000,
        "M": CANONICAL_MONTH_MILLIS,
    }
    return amount * multipliers.get(unit, 0)
