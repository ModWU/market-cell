from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from math import isfinite
from typing import Any, Literal, get_args

from market_cell.data.provenance import DataProvenance
from market_cell.inputs import InputSnapshot


FUNDING_OPEN_INTEREST_SNAPSHOT_SCHEMA_VERSION = (
    "funding_open_interest_snapshot.v1"
)
MAX_ABSOLUTE_FUNDING_RATE = 0.05
MAX_FUNDING_INTERVAL_HOURS = 24.0
DerivativesContractType = Literal["linear"]
FundingRateType = Literal["settled", "predicted"]


@dataclass(frozen=True)
class FundingOpenInterestPoint:
    timestamp_ms: int
    funding_rate: float
    open_interest_notional: float
    mark_price: float

    def __post_init__(self) -> None:
        if self.timestamp_ms < 0:
            raise ValueError(
                "funding/open-interest point timestamp must not be negative"
            )
        if not isfinite(self.funding_rate):
            raise ValueError("funding rate must be finite")
        if abs(self.funding_rate) > MAX_ABSOLUTE_FUNDING_RATE:
            raise ValueError(
                "funding rate exceeds the supported decimal-rate boundary"
            )
        if (
            not isfinite(self.open_interest_notional)
            or self.open_interest_notional <= 0
        ):
            raise ValueError("open-interest notional must be positive")
        if not isfinite(self.mark_price) or self.mark_price <= 0:
            raise ValueError("derivatives mark price must be positive")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FundingOpenInterestPoint":
        return cls(
            timestamp_ms=int(data["timestamp_ms"]),
            funding_rate=float(data["funding_rate"]),
            open_interest_notional=float(data["open_interest_notional"]),
            mark_price=float(data["mark_price"]),
        )


@dataclass(frozen=True)
class FundingOpenInterestSnapshot:
    target: str
    points: list[FundingOpenInterestPoint]
    funding_interval_hours: float
    funding_rate_type: FundingRateType
    sample_interval_ms: int
    notional_currency: str
    contract_type: DerivativesContractType
    provenance: DataProvenance
    schema_version: str = FUNDING_OPEN_INTEREST_SNAPSHOT_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.target.strip():
            raise ValueError("funding/open-interest target must not be empty")
        if not self.points:
            raise ValueError("funding/open-interest snapshot requires points")
        if (
            not isfinite(self.funding_interval_hours)
            or not 0 < self.funding_interval_hours <= MAX_FUNDING_INTERVAL_HOURS
        ):
            raise ValueError(
                "funding interval hours must be within (0, 24]"
            )
        if self.funding_rate_type not in get_args(FundingRateType):
            raise ValueError(
                "unsupported funding rate type: "
                f"{self.funding_rate_type}"
            )
        if self.sample_interval_ms <= 0:
            raise ValueError("sample interval must be positive")
        if not (
            2 <= len(self.notional_currency) <= 12
            and all(
                "A" <= character <= "Z" or character.isdigit()
                for character in self.notional_currency
            )
        ):
            raise ValueError(
                "open-interest notional currency must be a canonical "
                "uppercase asset code"
            )
        if self.contract_type != "linear":
            raise ValueError(
                "funding/open-interest snapshot currently supports only "
                "linear contracts"
            )
        if self.provenance.market_type != "perpetual_future":
            raise ValueError(
                "funding/open-interest snapshot requires perpetual_future provenance"
            )

        timestamps = [point.timestamp_ms for point in self.points]
        if timestamps != sorted(timestamps):
            raise ValueError(
                "funding/open-interest points must be sorted ascending"
            )
        if len(timestamps) != len(set(timestamps)):
            raise ValueError(
                "funding/open-interest point timestamps must be unique"
            )
        if timestamps[-1] != self.provenance.event_time_ms:
            raise ValueError(
                "latest funding/open-interest point must match provenance event time"
            )
        if self.schema_version != FUNDING_OPEN_INTEREST_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(
                "unsupported funding/open-interest schema version: "
                f"{self.schema_version}"
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FundingOpenInterestSnapshot":
        return cls(
            target=str(data["target"]),
            points=[
                FundingOpenInterestPoint.from_dict(item)
                for item in data["points"]
            ],
            funding_interval_hours=float(data["funding_interval_hours"]),
            funding_rate_type=data["funding_rate_type"],
            sample_interval_ms=int(data["sample_interval_ms"]),
            notional_currency=str(data["notional_currency"]),
            contract_type=data["contract_type"],
            provenance=DataProvenance.from_dict(data["provenance"]),
            schema_version=str(data["schema_version"]),
            metadata=deepcopy(data.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "points": [asdict(point) for point in self.points],
            "funding_interval_hours": self.funding_interval_hours,
            "funding_rate_type": self.funding_rate_type,
            "sample_interval_ms": self.sample_interval_ms,
            "notional_currency": self.notional_currency,
            "contract_type": self.contract_type,
            "provenance": self.provenance.to_dict(),
            "schema_version": self.schema_version,
            "metadata": deepcopy(self.metadata),
        }

    def to_input_snapshot(self, *, horizon: str) -> InputSnapshot:
        return InputSnapshot.create(
            input_kind="funding_open_interest_snapshot",
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
    def from_input_snapshot(
        cls,
        snapshot: InputSnapshot,
    ) -> "FundingOpenInterestSnapshot":
        if snapshot.input_kind != "funding_open_interest_snapshot":
            raise ValueError(
                f"input snapshot {snapshot.snapshot_id} is "
                f"{snapshot.input_kind}, not funding_open_interest_snapshot"
            )
        derivatives = cls.from_dict(snapshot.payload)
        mismatches: list[str] = []
        if derivatives.target != snapshot.target:
            mismatches.append("target")
        if derivatives.schema_version != snapshot.data_version:
            mismatches.append("data_version")
        if derivatives.provenance.source_provider != snapshot.source:
            mismatches.append("source")
        if mismatches:
            raise ValueError(
                "funding/open-interest snapshot "
                f"{snapshot.snapshot_id} envelope mismatch: "
                + ", ".join(mismatches)
            )
        return derivatives
