from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from math import isfinite
from typing import Any

from market_cell.data.provenance import DataProvenance
from market_cell.inputs import InputSnapshot


ORDER_BOOK_SNAPSHOT_SCHEMA_VERSION = "order_book_snapshot.v1"


@dataclass(frozen=True)
class OrderBookLevel:
    price: float
    quantity: float
    order_count: int | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.price) or self.price <= 0:
            raise ValueError("order book level price must be positive")
        if not isfinite(self.quantity) or self.quantity <= 0:
            raise ValueError("order book level quantity must be positive")
        if self.order_count is not None and self.order_count < 1:
            raise ValueError("order book level order_count must be positive")


@dataclass(frozen=True)
class OrderBookSnapshot:
    target: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    provenance: DataProvenance
    schema_version: str = ORDER_BOOK_SNAPSHOT_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.target.strip():
            raise ValueError("order book target must not be empty")
        if not self.bids or not self.asks:
            raise ValueError("order book requires bids and asks")
        bid_prices = [level.price for level in self.bids]
        ask_prices = [level.price for level in self.asks]
        if bid_prices != sorted(bid_prices, reverse=True):
            raise ValueError("order book bids must be sorted descending")
        if ask_prices != sorted(ask_prices):
            raise ValueError("order book asks must be sorted ascending")
        if len(bid_prices) != len(set(bid_prices)):
            raise ValueError("order book bid prices must be unique")
        if len(ask_prices) != len(set(ask_prices)):
            raise ValueError("order book ask prices must be unique")
        if self.best_bid >= self.best_ask:
            raise ValueError("order book must have a positive spread")
        if self.schema_version != ORDER_BOOK_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported order book schema version: {self.schema_version}"
            )

    @property
    def best_bid(self) -> float:
        return self.bids[0].price

    @property
    def best_ask(self) -> float:
        return self.asks[0].price

    @property
    def mid_price(self) -> float:
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread_bps(self) -> float:
        return (self.best_ask - self.best_bid) / self.mid_price * 10_000

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrderBookSnapshot":
        def level_from_dict(item: dict[str, Any]) -> OrderBookLevel:
            return OrderBookLevel(
                price=float(item["price"]),
                quantity=float(item["quantity"]),
                order_count=(
                    int(item["order_count"])
                    if item.get("order_count") is not None
                    else None
                ),
            )

        return cls(
            target=str(data["target"]),
            bids=[level_from_dict(item) for item in data["bids"]],
            asks=[level_from_dict(item) for item in data["asks"]],
            provenance=DataProvenance.from_dict(data["provenance"]),
            schema_version=str(data["schema_version"]),
            metadata=deepcopy(data.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "bids": [asdict(level) for level in self.bids],
            "asks": [asdict(level) for level in self.asks],
            "provenance": self.provenance.to_dict(),
            "schema_version": self.schema_version,
            "metadata": deepcopy(self.metadata),
        }

    def to_input_snapshot(self, *, horizon: str) -> InputSnapshot:
        return InputSnapshot.create(
            input_kind="order_book_snapshot",
            target=self.target,
            horizon=horizon,
            payload=self.to_dict(),
            data_version=self.schema_version,
            source=self.provenance.source_provider,
            metadata={
                "payload_schema_version": self.schema_version,
                "provenance": self.provenance.to_dict(),
            },
        )

    @classmethod
    def from_input_snapshot(cls, snapshot: InputSnapshot) -> "OrderBookSnapshot":
        if snapshot.input_kind != "order_book_snapshot":
            raise ValueError(
                f"input snapshot {snapshot.snapshot_id} is {snapshot.input_kind}, "
                "not order_book_snapshot"
            )
        order_book = cls.from_dict(snapshot.payload)
        mismatches: list[str] = []
        if order_book.target != snapshot.target:
            mismatches.append("target")
        if order_book.schema_version != snapshot.data_version:
            mismatches.append("data_version")
        if order_book.provenance.source_provider != snapshot.source:
            mismatches.append("source")
        if mismatches:
            raise ValueError(
                f"order book snapshot {snapshot.snapshot_id} envelope mismatch: "
                + ", ".join(mismatches)
            )
        return order_book
