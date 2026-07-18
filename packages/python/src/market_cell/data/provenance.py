from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, get_args


DATA_PROVENANCE_SCHEMA_VERSION = "data_provenance.v1"

MarketType = Literal[
    "spot",
    "perpetual_future",
    "futures",
    "index",
    "unknown",
]


@dataclass(frozen=True)
class DataProvenance:
    source_provider: str
    venue: str
    market_type: MarketType
    event_time_ms: int
    fetched_at_ms: int
    sequence: int | None = None
    source_event_id: str | None = None
    quality_flags: list[str] = field(default_factory=list)
    schema_version: str = DATA_PROVENANCE_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("source_provider", "venue"):
            if not getattr(self, field_name).strip():
                raise ValueError(
                    f"data provenance {field_name} must not be empty"
                )
        if self.market_type not in get_args(MarketType):
            raise ValueError(
                f"unsupported data provenance market_type: {self.market_type}"
            )
        if self.event_time_ms < 0 or self.fetched_at_ms < 0:
            raise ValueError("data provenance timestamps must not be negative")
        if self.sequence is not None and self.sequence < 0:
            raise ValueError("data provenance sequence must not be negative")
        if self.source_event_id is not None and not self.source_event_id.strip():
            raise ValueError(
                "data provenance source_event_id must not be empty"
            )
        if any(not flag.strip() for flag in self.quality_flags):
            raise ValueError("data provenance quality flags must not be empty")
        if len(self.quality_flags) != len(set(self.quality_flags)):
            raise ValueError("data provenance quality flags must be unique")
        if self.schema_version != DATA_PROVENANCE_SCHEMA_VERSION:
            raise ValueError(
                "unsupported data provenance schema version: "
                f"{self.schema_version}"
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DataProvenance":
        return cls(
            source_provider=str(data["source_provider"]),
            venue=str(data["venue"]),
            market_type=data["market_type"],
            event_time_ms=int(data["event_time_ms"]),
            fetched_at_ms=int(data["fetched_at_ms"]),
            sequence=(
                int(data["sequence"])
                if data.get("sequence") is not None
                else None
            ),
            source_event_id=(
                str(data["source_event_id"])
                if data.get("source_event_id") is not None
                else None
            ),
            quality_flags=[str(item) for item in data.get("quality_flags", [])],
            schema_version=str(data["schema_version"]),
            metadata=deepcopy(data.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
