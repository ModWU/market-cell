from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


EventHandler = Callable[["MarketCellEvent"], None]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MarketCellEvent:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self.events: list[MarketCellEvent] = []

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        self._handlers[event_name].append(handler)

    def emit(self, name: str, payload: dict[str, Any] | None = None) -> MarketCellEvent:
        event = MarketCellEvent(name=name, payload=payload or {})
        self.events.append(event)
        for handler in self._handlers.get(name, []):
            handler(event)
        for handler in self._handlers.get("*", []):
            handler(event)
        return event
