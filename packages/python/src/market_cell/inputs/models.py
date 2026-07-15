from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from market_cell.events import utc_now_iso
from market_cell.hashing import canonical_json_hash_and_size, stable_json_hash
from market_cell.models import AnalysisRequest

if TYPE_CHECKING:
    from market_cell.features import FeatureSnapshot


INPUT_SNAPSHOT_SCHEMA_VERSION = "input_snapshot.v1"
INPUT_SNAPSHOT_AUDIT_SCHEMA_VERSION = "input_snapshot_audit.v1"
INPUT_REFERENCE_SCHEMA_VERSION = "input_reference.v1"
INPUT_RESOLUTION_RECORD_SCHEMA_VERSION = "input_resolution_record.v1"

InputKind = Literal["analysis_request", "candle_batch", "feature_snapshot"]
InputResolutionStatus = Literal["succeeded", "failed"]


def _input_identity_hash(
    *,
    input_kind: InputKind,
    target: str,
    horizon: str,
    content_hash: str,
    data_version: str,
    source: str,
) -> str:
    return stable_json_hash(
        {
            "content_hash": content_hash,
            "data_version": data_version,
            "horizon": horizon,
            "input_kind": input_kind,
            "source": source,
            "target": target,
        }
    )


def _input_snapshot_id(
    *,
    input_kind: InputKind,
    target: str,
    horizon: str,
    content_hash: str,
    data_version: str,
    source: str,
) -> str:
    identity_hash = _input_identity_hash(
        input_kind=input_kind,
        target=target,
        horizon=horizon,
        content_hash=content_hash,
        data_version=data_version,
        source=source,
    )
    return f"snapshot:{input_kind}:{identity_hash[:24]}"


@dataclass(frozen=True)
class InputReference:
    reference_id: str
    snapshot_id: str
    input_kind: InputKind
    uri: str
    content_hash: str
    data_version: str
    source: str
    target: str
    horizon: str
    payload_size_bytes: int
    schema_version: str = INPUT_REFERENCE_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InputSnapshot:
    snapshot_id: str
    input_kind: InputKind
    target: str
    horizon: str
    content_hash: str
    data_version: str
    source: str
    payload: dict[str, Any]
    payload_size_bytes: int
    created_at: str = field(default_factory=utc_now_iso)
    schema_version: str = INPUT_SNAPSHOT_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        input_kind: InputKind,
        target: str,
        horizon: str,
        payload: dict[str, Any],
        data_version: str,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> "InputSnapshot":
        return cls._create_from_owned_payload(
            input_kind=input_kind,
            target=target,
            horizon=horizon,
            payload=deepcopy(payload),
            data_version=data_version,
            source=source,
            metadata=deepcopy(metadata or {}),
        )

    @classmethod
    def _create_from_owned_payload(
        cls,
        *,
        input_kind: InputKind,
        target: str,
        horizon: str,
        payload: dict[str, Any],
        data_version: str,
        source: str,
        metadata: dict[str, Any],
    ) -> "InputSnapshot":
        content_hash, payload_size_bytes = canonical_json_hash_and_size(payload)
        return cls(
            snapshot_id=_input_snapshot_id(
                input_kind=input_kind,
                target=target,
                horizon=horizon,
                content_hash=content_hash,
                data_version=data_version,
                source=source,
            ),
            input_kind=input_kind,
            target=target,
            horizon=horizon,
            content_hash=content_hash,
            data_version=data_version,
            source=source,
            payload=payload,
            payload_size_bytes=payload_size_bytes,
            metadata=metadata,
        )

    @classmethod
    def from_analysis_request(
        cls,
        request: AnalysisRequest,
        *,
        data_version: str = "analysis_request.v1",
        source: str = "analysis_request",
        metadata: dict[str, Any] | None = None,
    ) -> "InputSnapshot":
        return cls._create_from_owned_payload(
            input_kind="analysis_request",
            target=request.target,
            horizon=request.horizon,
            payload=asdict(request),
            data_version=data_version,
            source=source,
            metadata=deepcopy(metadata or {}),
        )

    @classmethod
    def from_feature_snapshot(
        cls,
        feature_snapshot: "FeatureSnapshot",
        *,
        target: str,
        horizon: str,
        source: str = "feature_runtime",
        metadata: dict[str, Any] | None = None,
    ) -> "InputSnapshot":
        return cls._create_from_owned_payload(
            input_kind="feature_snapshot",
            target=target,
            horizon=horizon,
            payload=feature_snapshot.to_dict(),
            data_version=feature_snapshot.feature_version,
            source=source,
            metadata=deepcopy(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_audit_dict(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload.pop("payload")
        payload["schema_version"] = INPUT_SNAPSHOT_AUDIT_SCHEMA_VERSION
        return payload

    def to_run_metadata(self) -> dict[str, Any]:
        return {"input_snapshot_audit": self.to_audit_dict()}

    def to_reference(
        self,
        uri: str | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> InputReference:
        identity = self.snapshot_id.removeprefix("snapshot:")
        return InputReference(
            reference_id=f"input:{identity}",
            snapshot_id=self.snapshot_id,
            input_kind=self.input_kind,
            uri=uri or f"memory://market-cell-input/{self.snapshot_id}",
            content_hash=self.content_hash,
            data_version=self.data_version,
            source=self.source,
            target=self.target,
            horizon=self.horizon,
            payload_size_bytes=self.payload_size_bytes,
            metadata=deepcopy(metadata or {}),
        )

    def expected_snapshot_id(self) -> str:
        return _input_snapshot_id(
            input_kind=self.input_kind,
            target=self.target,
            horizon=self.horizon,
            content_hash=self.content_hash,
            data_version=self.data_version,
            source=self.source,
        )

    def to_analysis_request(self) -> AnalysisRequest:
        if self.input_kind != "analysis_request":
            raise ValueError(
                f"input snapshot {self.snapshot_id} is {self.input_kind}, not analysis_request"
            )
        return AnalysisRequest.from_dict(self.payload)


@dataclass(frozen=True)
class InputResolutionRecord:
    node_id: str
    reference_id: str
    input_kind: InputKind
    resolver: str
    status: InputResolutionStatus
    cache_hit: bool
    expected_content_hash: str
    actual_content_hash: str | None
    expected_payload_size_bytes: int
    actual_payload_size_bytes: int | None
    data_version: str
    source: str
    resolved_at: str = field(default_factory=utc_now_iso)
    error: str | None = None
    schema_version: str = INPUT_RESOLUTION_RECORD_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
