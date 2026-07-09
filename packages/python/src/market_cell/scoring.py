from market_cell.models import CellResult


DIRECTION_VALUE = {
    "bullish": 1.0,
    "bearish": -1.0,
    "neutral": 0.0,
    "conflict": 0.0,
}


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def score(direction: str, strength: float, confidence: float) -> float:
    return round(DIRECTION_VALUE.get(direction, 0.0) * clamp(strength) * clamp(confidence) / 100.0, 4)


def direction_from_score(value: float, bullish_threshold: float = 12.0, bearish_threshold: float = -12.0) -> str:
    if value >= bullish_threshold:
        return "bullish"
    if value <= bearish_threshold:
        return "bearish"
    if abs(value) < 4:
        return "neutral"
    return "conflict"


def weighted_average(results: list[CellResult], weights: dict[str, float]) -> float:
    total_weight = 0.0
    total = 0.0
    for result in results:
        weight = weights.get(result.cell_id, 1.0)
        total += result.score * weight
        total_weight += weight
    if total_weight == 0:
        return 0.0
    return round(total / total_weight, 4)
