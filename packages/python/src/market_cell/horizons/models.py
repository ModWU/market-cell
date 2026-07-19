from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Literal

from market_cell.hashing import canonical_json_hash_and_size
from market_cell.models import AnalysisReport, AnalysisRequest


MULTI_HORIZON_REQUEST_SCHEMA_VERSION = "multi_horizon_request.v1"
MULTI_HORIZON_ANALYSIS_SCHEMA_VERSION = "multi_horizon_analysis.v1"
MINIMUM_HORIZON_COUNT = 2
MAXIMUM_HORIZON_COUNT = 8

AggregationStatus = Literal["not_computed"]

_BATCH_ID_PATTERN = re.compile(r"^multi-horizon:[a-f0-9]{32}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class MultiHorizonRequest:
    target: str
    as_of_ms: int
    requests: list[AnalysisRequest]
    schema_version: str = MULTI_HORIZON_REQUEST_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MultiHorizonRequest":
        return cls(
            target=str(data["target"]),
            as_of_ms=int(data["as_of_ms"]),
            requests=[
                AnalysisRequest.from_dict(item)
                for item in data.get("requests", [])
            ],
            schema_version=str(data.get("schema_version", "")),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def identity_payload(self) -> dict[str, Any]:
        """Return only fields that can affect horizon analysis behavior."""
        return {
            "target": self.target,
            "as_of_ms": self.as_of_ms,
            "requests": [asdict(request) for request in self.requests],
            "schema_version": self.schema_version,
        }

    def content_hash_and_size(self) -> tuple[str, int]:
        return canonical_json_hash_and_size(self.identity_payload())

    @property
    def content_hash(self) -> str:
        content_hash, _ = self.content_hash_and_size()
        return content_hash

    @property
    def payload_size_bytes(self) -> int:
        _, payload_size_bytes = self.content_hash_and_size()
        return payload_size_bytes

    @property
    def request_id(self) -> str:
        return f"multi-horizon-request:{self.content_hash[:24]}"

    @property
    def horizon_order(self) -> list[str]:
        return [request.horizon for request in self.requests]


@dataclass(frozen=True)
class MultiHorizonAnalysis:
    batch_id: str
    request_id: str
    request_hash: str
    target: str
    as_of_ms: int
    horizon_order: list[str]
    reports: list[AnalysisReport]
    graph_id: str
    graph_version: str
    graph_content_hash: str
    formula_versions: dict[str, str]
    created_at: str
    aggregation_status: AggregationStatus = "not_computed"
    schema_version: str = MULTI_HORIZON_ANALYSIS_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if _BATCH_ID_PATTERN.fullmatch(self.batch_id) is None:
            raise ValueError("multi-horizon batch_id must use the canonical id")
        if _SHA256_PATTERN.fullmatch(self.request_hash) is None:
            raise ValueError("multi-horizon request_hash must be SHA-256")
        expected_request_id = (
            f"multi-horizon-request:{self.request_hash[:24]}"
        )
        if self.request_id != expected_request_id:
            raise ValueError(
                "multi-horizon request_id must match request_hash"
            )
        if _SHA256_PATTERN.fullmatch(self.graph_content_hash) is None:
            raise ValueError(
                "multi-horizon graph_content_hash must be SHA-256"
            )
        if not self.target.strip() or self.target != self.target.strip():
            raise ValueError("multi-horizon target must be canonical")
        if self.as_of_ms < 0:
            raise ValueError("multi-horizon as_of_ms must not be negative")
        if not self.graph_id.strip() or not self.graph_version.strip():
            raise ValueError("multi-horizon graph identity must not be empty")
        if not self.formula_versions or any(
            not cell_id.strip() or not version.strip()
            for cell_id, version in self.formula_versions.items()
        ):
            raise ValueError(
                "multi-horizon formula versions must be complete"
            )
        if not self.created_at.strip():
            raise ValueError("multi-horizon created_at must not be empty")
        if self.aggregation_status != "not_computed":
            raise ValueError(
                "MultiHorizonAnalysis cannot contain an aggregate decision"
            )
        if self.schema_version != MULTI_HORIZON_ANALYSIS_SCHEMA_VERSION:
            raise ValueError(
                "unsupported multi-horizon analysis schema version: "
                f"{self.schema_version}"
            )
        if not (
            MINIMUM_HORIZON_COUNT
            <= len(self.horizon_order)
            <= MAXIMUM_HORIZON_COUNT
        ):
            raise ValueError(
                "multi-horizon horizon count must be between "
                f"{MINIMUM_HORIZON_COUNT} and {MAXIMUM_HORIZON_COUNT}"
            )
        if len(self.horizon_order) != len(set(self.horizon_order)):
            raise ValueError("multi-horizon horizons must be unique")
        if len(self.horizon_order) != len(self.reports):
            raise ValueError(
                "multi-horizon reports must match the declared horizon order"
            )
        report_horizons = [report.horizon for report in self.reports]
        if report_horizons != self.horizon_order:
            raise ValueError(
                "multi-horizon report order does not match horizon_order"
            )
        if any(report.target != self.target for report in self.reports):
            raise ValueError(
                "multi-horizon report target does not match batch target"
            )
        if any(
            report.decision.target != report.target
            or report.decision.horizon != report.horizon
            for report in self.reports
        ):
            raise ValueError(
                "multi-horizon child decision scope does not match its report"
            )
        if any(
            report.formula_versions != self.formula_versions
            for report in self.reports
        ):
            raise ValueError(
                "multi-horizon reports do not share one formula version set"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
